from datetime import UTC, datetime

import pytest

from agent_memory.domain.enums import ScopeKind
from agent_memory.domain.errors import InvalidEvent
from agent_memory.domain.events import EventDraft, EventType
from agent_memory.domain.models import MemoryScope

NOW = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)


def event_draft(**changes: object) -> EventDraft:
    values: dict[str, object] = {
        "idempotency_key": "session-42-build-7",
        "session_id": "session-42",
        "sequence_number": 7,
        "event_type": EventType.TOOL_RESULT,
        "agent_id": "coding_agent",
        "occurred_at": NOW,
        "scope": MemoryScope(ScopeKind.WORKSPACE, "project-a", None),
        "payload": {"tool_name": "build", "exit_code": 1},
    }
    values.update(changes)
    return EventDraft(**values)  # type: ignore[arg-type]


def test_event_hash_is_stable_across_payload_key_order() -> None:
    first = event_draft(payload={"exit_code": 1, "tool_name": "build"})
    second = event_draft(payload={"tool_name": "build", "exit_code": 1})

    assert first.request_hash() == second.request_hash()


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"sequence_number": 0}, "sequence_number"),
        ({"idempotency_key": "  "}, "idempotency_key"),
        ({"session_id": ""}, "session_id"),
        ({"agent_id": ""}, "agent_id"),
        ({"occurred_at": NOW.replace(tzinfo=None)}, "timezone"),
    ],
)
def test_event_rejects_invalid_identity_and_ordering_fields(
    changes: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(InvalidEvent, match=message):
        event_draft(**changes)


def test_event_rejects_payload_deeper_than_four_containers() -> None:
    with pytest.raises(InvalidEvent, match="depth"):
        event_draft(payload={"one": {"two": {"three": {"four": {"five": 1}}}}})


def test_event_rejects_payload_larger_than_64_kib() -> None:
    with pytest.raises(InvalidEvent, match="65,536"):
        event_draft(payload={"summary": "x" * 65_537})
