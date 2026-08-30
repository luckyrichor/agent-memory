from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import UUID

import pytest

from agent_memory.application.event_commands import IngestEventBatchCommand
from agent_memory.application.event_ingestion import EventIngestionService
from agent_memory.application.outbox_dispatcher import OutboxDispatcher
from agent_memory.domain.enums import ScopeKind
from agent_memory.domain.errors import InvalidEvent
from agent_memory.domain.events import EventDraft, EventType
from agent_memory.domain.models import MemoryScope
from agent_memory.domain.principal import RequestPrincipal
from agent_memory.infrastructure.in_memory_events import InMemoryEventIngestionRepository

TENANT_ID = UUID("33000000-0000-0000-0000-000000000001")
USER_ID = UUID("33000000-0000-0000-0000-000000000002")
NOW = datetime(2026, 8, 30, 17, 0, tzinfo=UTC)


def principal() -> RequestPrincipal:
    return RequestPrincipal(
        tenant_id=TENANT_ID,
        user_id=USER_ID,
        roles=frozenset({"developer"}),
        permissions=frozenset({"memory:write"}),
        allowed_workspace_ids=frozenset({"project-a"}),
    )


def event() -> EventDraft:
    return EventDraft(
        idempotency_key="dispatch-event-1",
        session_id="dispatch-session",
        sequence_number=1,
        event_type=EventType.TOOL_RESULT,
        agent_id="coding_agent",
        occurred_at=NOW,
        scope=MemoryScope(ScopeKind.WORKSPACE, "project-a", None),
        payload={"tool_name": "build", "exit_code": 1, "summary": "failed"},
    )


def id_source() -> Iterator[UUID]:
    number = 10
    while True:
        yield UUID(f"33000000-0000-0000-0000-{number:012d}")
        number += 1


@pytest.mark.asyncio
async def test_replayed_dispatch_creates_one_job_and_publishes_outbox() -> None:
    ids = id_source()
    store = InMemoryEventIngestionRepository(new_id=lambda: next(ids), now=lambda: NOW)
    await EventIngestionService(store).ingest_batch(
        IngestEventBatchCommand((event(),)), principal()
    )
    dispatcher = OutboxDispatcher(store, "coding-failure-rule-v1")

    assert await dispatcher.dispatch_once(TENANT_ID, 10) == 1
    assert await dispatcher.dispatch_once(TENANT_ID, 10) == 0
    assert store.job_count == 1
    assert store.outbox_status == "published"


@pytest.mark.asyncio
async def test_dispatch_batch_size_is_bounded() -> None:
    ids = id_source()
    store = InMemoryEventIngestionRepository(new_id=lambda: next(ids), now=lambda: NOW)
    dispatcher = OutboxDispatcher(store, "coding-failure-rule-v1")

    with pytest.raises(InvalidEvent, match="between 1 and 100"):
        await dispatcher.dispatch_once(TENANT_ID, 0)
    with pytest.raises(InvalidEvent, match="between 1 and 100"):
        await dispatcher.dispatch_once(TENANT_ID, 101)
