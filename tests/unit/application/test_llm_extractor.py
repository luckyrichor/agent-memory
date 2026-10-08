import json
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

import httpx
import pytest

from agent_memory.domain.enums import AuthorityLevel, ScopeKind, VerificationStatus
from agent_memory.domain.events import Event, EventDraft, EventType
from agent_memory.domain.models import MemoryScope
from agent_memory.infrastructure.llm_extractor import LLMExtractor


def event(summary: str = "x86 dependency failed on arm64") -> Event:
    now = datetime.now(UTC)
    return Event(
        UUID(int=1),
        UUID(int=2),
        EventDraft(
            "key",
            "session",
            1,
            EventType.TOOL_RESULT,
            "agent",
            now,
            MemoryScope(ScopeKind.WORKSPACE, "private", None),
            {"summary": summary, "tool_name": "build", "exit_code": 1},
        ),
        UUID(int=3),
        now,
    )


def extractor(content: object, status: int = 200) -> LLMExtractor:
    def respond(request: httpx.Request) -> httpx.Response:
        assert "private" not in request.content.decode()
        return httpx.Response(
            status,
            json={
                "choices": [{"message": {"content": json.dumps(content)}}],
            },
        )

    return LLMExtractor(
        "https://provider.test/chat", "fixture", "test", transport=httpx.MockTransport(respond)
    )


async def test_scope_and_authority_are_server_owned() -> None:
    model = extractor({"memories": [{"content": "Check target architecture before building"}]})
    result = await model.extract(event())
    assert result[0].scope == event().draft.scope
    assert result[0].authority_level == AuthorityLevel.AGENT_INFERENCE
    assert result[0].verification_status == VerificationStatus.UNVERIFIED
    assert model.last_reason == "LLM_EXTRACTED"


@pytest.mark.parametrize(
    "summary",
    ["password=abc", "API_KEY=test", "密钥 abc", "contact alice@example.test", "phone 13812345678"],
)
async def test_sensitive_input_never_calls_provider(summary: str) -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise AssertionError("sensitive input sent")

    model = LLMExtractor(
        "https://provider.test/chat", "fixture", "test", transport=httpx.MockTransport(fail)
    )
    assert await model.extract(event(summary)) == ()
    assert model.last_reason == "INPUT_POLICY_REJECTED"


async def test_sensitive_output_rejected() -> None:
    model = extractor({"memories": [{"content": "password abc"}]})
    assert await model.extract(event()) == ()
    assert model.last_reason == "OUTPUT_POLICY_REJECTED"


@pytest.mark.parametrize(
    "output",
    [
        {"memories": [{"content": "lesson", "scope": "tenant"}]},
        {"memories": "bad"},
        {},
        {"memories": [{"content": "x"}] * 4},
    ],
)
async def test_malformed_or_privilege_escalation_falls_back(output: object) -> None:
    model = extractor(output)
    result = await model.extract(event())
    assert result[0].content == "x86 dependency failed on arm64"
    assert result[0].scope == event().draft.scope
    assert model.last_reason == "RULE_FALLBACK"


@pytest.mark.parametrize("status", [401])
async def test_provider_unavailable_falls_back(status: int) -> None:
    model = extractor({}, status)
    assert len(await model.extract(event())) == 1
    assert model.last_reason == "RULE_FALLBACK"


async def test_empty_extraction_is_not_provider_failure() -> None:
    model = extractor({"memories": []})
    assert await model.extract(event()) == ()
    assert model.last_reason == "LLM_EXTRACTED"


@pytest.mark.parametrize("kind", [EventType.TASK_COMPLETED, EventType.USER_CONFIRMED])
async def test_model_handles_non_build_events(kind: EventType) -> None:
    original = event("Completed a deployment after checking configuration")
    non_build = replace(
        original,
        draft=replace(
            original.draft, event_type=kind, payload={"summary": "Check config before deployment"}
        ),
    )
    model = extractor({"memories": [{"content": "Check configuration before deploying"}]})
    assert len(await model.extract(non_build)) == 1
    assert model.last_reason == "LLM_EXTRACTED"


@pytest.mark.parametrize("status", [429, 500, 503])
async def test_transient_provider_error_does_not_fall_back(status: int) -> None:
    from agent_memory.domain.errors import RetryableExtractionError

    model = extractor({}, status)
    with pytest.raises(RetryableExtractionError):
        await model.extract(event())
    assert model.last_reason == "PROVIDER_RETRY"
