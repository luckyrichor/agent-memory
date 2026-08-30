from datetime import UTC, datetime
from uuid import UUID

import pytest

from agent_memory.application.extraction import CodingFailureRuleExtractor
from agent_memory.domain.enums import (
    AuthorityLevel,
    MemoryType,
    ScopeKind,
    VerificationStatus,
)
from agent_memory.domain.events import Event, EventDraft, EventType
from agent_memory.domain.models import MemoryScope

TENANT_ID = UUID("34000000-0000-0000-0000-000000000001")
USER_ID = UUID("34000000-0000-0000-0000-000000000002")
EVENT_ID = UUID("34000000-0000-0000-0000-000000000003")
NOW = datetime(2026, 8, 30, 18, 0, tzinfo=UTC)


def tool_event(
    *,
    tool_name: str = "build",
    exit_code: int = 1,
    summary: str = "  x86 dependency failed on arm64  ",
    event_type: EventType = EventType.TOOL_RESULT,
) -> Event:
    return Event(
        tenant_id=TENANT_ID,
        event_id=EVENT_ID,
        actor_user_id=USER_ID,
        received_at=NOW,
        draft=EventDraft(
            idempotency_key="extract-event-1",
            session_id="extract-session",
            sequence_number=1,
            event_type=event_type,
            agent_id="coding_agent",
            occurred_at=NOW,
            scope=MemoryScope(ScopeKind.WORKSPACE, "project-a", None),
            payload={"tool_name": tool_name, "exit_code": exit_code, "summary": summary},
        ),
    )


@pytest.mark.asyncio
async def test_failed_build_creates_scope_preserving_episodic_candidate() -> None:
    event = tool_event()

    candidates = await CodingFailureRuleExtractor().extract(event)

    assert len(candidates) == 1
    assert candidates[0].content == "x86 dependency failed on arm64"
    assert candidates[0].scope == event.draft.scope
    assert candidates[0].memory_type is MemoryType.EPISODIC
    assert candidates[0].confidence == 1.0
    assert candidates[0].utility == 0.5
    assert candidates[0].authority_level is AuthorityLevel.TOOL_VERIFIED
    assert candidates[0].verification_status is VerificationStatus.VERIFIED


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "event",
    [
        tool_event(exit_code=0),
        tool_event(tool_name="read_file"),
        tool_event(summary="   "),
        tool_event(event_type=EventType.TASK_COMPLETED),
    ],
)
async def test_non_failure_events_produce_no_candidate(event: Event) -> None:
    assert await CodingFailureRuleExtractor().extract(event) == ()
