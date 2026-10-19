import json
from datetime import UTC, datetime
from uuid import UUID

import httpx
import pytest

from agent_memory.domain.enums import ScopeKind
from agent_memory.domain.models import MemoryScope
from agent_memory.evals.api_import import import_conversation, source_time
from agent_memory.evals.datasets import Conversation, Document
from agent_memory.sdk import MemoryClient


async def test_full_import_preserves_roles_parts_event_mapping_and_idempotency():
    requests = []

    def respond(request):
        assert request.url.path == "/v1/events:batch"
        event = json.loads(request.content)["events"][0]
        requests.append(event)
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "event_id": "10000000-0000-0000-0000-000000000001",
                        "idempotency_key": event["idempotency_key"],
                        "disposition": "accepted",
                    }
                ]
            },
        )

    conv = Conversation(
        conversation_id="c",
        questions=[],
        documents=[
            Document(
                source_id="a",
                session_id="s",
                role="assistant",
                text="x" * 4001,
                occurred_at="2023/04/10 (Mon) 17:50",
            )
        ],
    )
    scope = MemoryScope(ScopeKind.WORKSPACE, "eval", None)
    async with httpx.AsyncClient(
        base_url="https://api.test", transport=httpx.MockTransport(respond)
    ) as http:
        sdk = MemoryClient(http, token="unit-test-only")
        first = await import_conversation(sdk, conv, scope, mode="full")
        await import_conversation(sdk, conv, scope, mode="full")
    assert len(first) == 2 and all("event_id" in row and "version_id" not in row for row in first)
    assert "".join(r["payload"]["summary"] for r in requests[:2]) == "x" * 4001
    assert all(r["payload"]["role"] == "assistant" for r in requests)
    assert [r["sequence_number"] for r in requests[:2]] == [1, 2]
    assert requests[:2] == requests[2:]
    assert len({r["idempotency_key"] for r in requests[:2]}) == 2


async def test_direct_import_uses_sdk_and_records_exact_source_ids():
    def respond(request):
        assert request.url.path == "/v1/memories"
        assert json.loads(request.content)["content"] == "source text"
        return httpx.Response(
            200,
            json={
                "tenant_id": str(UUID(int=1)),
                "memory_id": str(UUID(int=2)),
                "version_id": str(UUID(int=3)),
                "revision": 1,
                "status": "active",
            },
        )

    conv = Conversation(
        conversation_id="c",
        questions=[],
        documents=[Document(source_id="a", session_id="s", role="user", text="source text")],
    )
    scope = MemoryScope(ScopeKind.WORKSPACE, "eval", None)
    async with httpx.AsyncClient(
        base_url="https://api.test", transport=httpx.MockTransport(respond)
    ) as http:
        rows = await import_conversation(
            MemoryClient(http, token="unit-test-only"), conv, scope, mode="direct"
        )
    assert rows[0]["memory_id"] == str(UUID(int=2)) and rows[0]["source_id"] == "a"
    assert "source text" not in json.dumps(rows)


def test_source_time_does_not_fabricate_missing_chronology():
    assert source_time("2023/04/10 (Mon) 17:50") == datetime(2023, 4, 10, 17, 50, tzinfo=UTC)
    for invalid in [None, "2020-01-01", "not a time"]:
        with pytest.raises(ValueError):
            source_time(invalid)
