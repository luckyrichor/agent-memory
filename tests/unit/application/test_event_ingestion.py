from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import UUID

import pytest

from agent_memory.application.event_commands import IngestEventBatchCommand
from agent_memory.application.event_ingestion import EventIngestionService
from agent_memory.domain.enums import ScopeKind
from agent_memory.domain.errors import (
    EventIdempotencyConflict,
    EventSequenceConflict,
    InvalidEvent,
    MemoryScopeForbidden,
)
from agent_memory.domain.events import EventDraft, EventType
from agent_memory.domain.models import MemoryScope
from agent_memory.domain.principal import RequestPrincipal
from agent_memory.infrastructure.in_memory_events import InMemoryEventIngestionRepository

TENANT_ID = UUID("10000000-0000-0000-0000-000000000001")
USER_ID = UUID("10000000-0000-0000-0000-000000000002")
EVENT_1 = UUID("10000000-0000-0000-0000-000000000003")
OUTBOX_1 = UUID("10000000-0000-0000-0000-000000000004")
EVENT_2 = UUID("10000000-0000-0000-0000-000000000005")
OUTBOX_2 = UUID("10000000-0000-0000-0000-000000000006")
NOW = datetime(2026, 8, 30, 14, 0, tzinfo=UTC)


def principal(*, workspaces: frozenset[str] = frozenset({"project-a"})) -> RequestPrincipal:
    return RequestPrincipal(
        tenant_id=TENANT_ID,
        user_id=USER_ID,
        roles=frozenset({"developer"}),
        permissions=frozenset({"memory:write"}),
        allowed_workspace_ids=workspaces,
    )


def draft(
    *,
    key: str = "build-1",
    sequence: int = 1,
    summary: str = "arm64 build failed",
) -> EventDraft:
    return EventDraft(
        idempotency_key=key,
        session_id="session-1",
        sequence_number=sequence,
        event_type=EventType.TOOL_RESULT,
        agent_id="coding_agent",
        occurred_at=NOW,
        scope=MemoryScope(ScopeKind.WORKSPACE, "project-a", None),
        payload={"tool_name": "build", "exit_code": 1, "summary": summary},
    )


def make_service() -> tuple[EventIngestionService, InMemoryEventIngestionRepository]:
    ids: Iterator[UUID] = iter((EVENT_1, OUTBOX_1, EVENT_2, OUTBOX_2))
    repository = InMemoryEventIngestionRepository(new_id=lambda: next(ids), now=lambda: NOW)
    return EventIngestionService(repository), repository


@pytest.mark.asyncio
async def test_batch_replay_returns_original_id_without_new_outbox() -> None:
    service, repository = make_service()
    command = IngestEventBatchCommand((draft(),))

    first = await service.ingest_batch(command, principal())
    replay = await service.ingest_batch(command, principal())

    assert first[0].disposition == "accepted"
    assert replay[0].disposition == "duplicate"
    assert replay[0].event_id == first[0].event_id == EVENT_1
    assert repository.event_count == 1
    assert repository.outbox_count == 1


@pytest.mark.asyncio
async def test_changed_idempotent_replay_rolls_back_whole_batch() -> None:
    service, repository = make_service()
    await service.ingest_batch(IngestEventBatchCommand((draft(),)), principal())

    with pytest.raises(EventIdempotencyConflict):
        await service.ingest_batch(
            IngestEventBatchCommand(
                (
                    draft(key="build-2", sequence=2),
                    draft(key="build-1", sequence=1, summary="changed"),
                )
            ),
            principal(),
        )

    assert repository.event_count == 1
    assert repository.outbox_count == 1


@pytest.mark.asyncio
async def test_session_sequence_collision_is_rejected() -> None:
    service, repository = make_service()
    await service.ingest_batch(IngestEventBatchCommand((draft(),)), principal())

    with pytest.raises(EventSequenceConflict):
        await service.ingest_batch(
            IngestEventBatchCommand((draft(key="another-key", sequence=1),)),
            principal(),
        )

    assert repository.event_count == 1


@pytest.mark.asyncio
async def test_workspace_scope_requires_access_before_repository_write() -> None:
    service, repository = make_service()

    with pytest.raises(MemoryScopeForbidden):
        await service.ingest_batch(
            IngestEventBatchCommand((draft(),)),
            principal(workspaces=frozenset({"project-b"})),
        )

    assert repository.event_count == 0
    assert repository.outbox_count == 0


@pytest.mark.asyncio
async def test_batch_size_is_bounded_from_one_to_one_hundred() -> None:
    service, repository = make_service()

    with pytest.raises(InvalidEvent, match="between 1 and 100"):
        await service.ingest_batch(IngestEventBatchCommand(()), principal())
    with pytest.raises(InvalidEvent, match="between 1 and 100"):
        await service.ingest_batch(
            IngestEventBatchCommand(tuple(draft(key=f"key-{n}", sequence=n) for n in range(1, 102))),
            principal(),
        )

    assert repository.event_count == 0
