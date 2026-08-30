from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy import func, select

from agent_memory.domain.enums import ScopeKind
from agent_memory.domain.errors import EventIdempotencyConflict, EventSequenceConflict
from agent_memory.domain.events import EventDraft, EventType
from agent_memory.domain.models import MemoryScope
from agent_memory.domain.principal import RequestPrincipal
from agent_memory.infrastructure.db import (
    create_engine,
    create_session_factory,
    session_for_principal,
)
from agent_memory.infrastructure.event_repositories import PostgresEventIngestionRepository
from agent_memory.infrastructure.orm import EventRow, OutboxMessageRow

TENANT_ID = UUID("31000000-0000-0000-0000-000000000001")
USER_ID = UUID("31000000-0000-0000-0000-000000000002")
NOW = datetime(2026, 8, 30, 16, 0, tzinfo=UTC)


def principal() -> RequestPrincipal:
    return RequestPrincipal(
        tenant_id=TENANT_ID,
        user_id=USER_ID,
        roles=frozenset({"developer"}),
        permissions=frozenset({"memory:write"}),
        allowed_workspace_ids=frozenset({"project-a"}),
    )


def draft(*, key: str, sequence: int, summary: str = "arm64 build failed") -> EventDraft:
    return EventDraft(
        idempotency_key=key,
        session_id="integration-session",
        sequence_number=sequence,
        event_type=EventType.TOOL_RESULT,
        agent_id="coding_agent",
        occurred_at=NOW,
        scope=MemoryScope(ScopeKind.WORKSPACE, "project-a", None),
        payload={"tool_name": "build", "exit_code": 1, "summary": summary},
    )


def id_source(start: int) -> Iterator[UUID]:
    number = start
    while True:
        yield UUID(f"31000000-0000-0000-0000-{number:012d}")
        number += 1


@pytest.mark.asyncio
async def test_postgres_ingestion_is_atomic_and_idempotent(app_database_url: str) -> None:
    engine = create_engine(app_database_url)
    sessions = create_session_factory(engine)
    ids = id_source(100)
    command = (draft(key="integration-build-1", sequence=1),)

    async with session_for_principal(sessions, principal()) as session:
        repository = PostgresEventIngestionRepository(
            session, new_id=lambda: next(ids), now=lambda: NOW
        )
        first = await repository.ingest_batch(TENANT_ID, USER_ID, command)

    async with session_for_principal(sessions, principal()) as session:
        repository = PostgresEventIngestionRepository(
            session, new_id=lambda: next(ids), now=lambda: NOW
        )
        replay = await repository.ingest_batch(TENANT_ID, USER_ID, command)
        event_count = await session.scalar(
            select(func.count()).select_from(EventRow).where(EventRow.tenant_id == TENANT_ID)
        )
        outbox_count = await session.scalar(
            select(func.count())
            .select_from(OutboxMessageRow)
            .where(OutboxMessageRow.tenant_id == TENANT_ID)
        )

    assert first[0].disposition == "accepted"
    assert replay[0].disposition == "duplicate"
    assert replay[0].event_id == first[0].event_id
    assert event_count == 1
    assert outbox_count == 1
    await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_ingestion_conflict_leaves_no_partial_batch_rows(
    app_database_url: str,
) -> None:
    engine = create_engine(app_database_url)
    sessions = create_session_factory(engine)
    ids = id_source(200)
    original = draft(key="integration-build-2", sequence=2)

    async with session_for_principal(sessions, principal()) as session:
        repository = PostgresEventIngestionRepository(
            session, new_id=lambda: next(ids), now=lambda: NOW
        )
        await repository.ingest_batch(TENANT_ID, USER_ID, (original,))

    with pytest.raises(EventIdempotencyConflict):
        async with session_for_principal(sessions, principal()) as session:
            repository = PostgresEventIngestionRepository(
                session, new_id=lambda: next(ids), now=lambda: NOW
            )
            await repository.ingest_batch(
                TENANT_ID,
                USER_ID,
                (
                    draft(key="must-rollback", sequence=3),
                    draft(key="integration-build-2", sequence=2, summary="changed"),
                ),
            )

    async with session_for_principal(sessions, principal()) as session:
        rolled_back = await session.scalar(
            select(func.count())
            .select_from(EventRow)
            .where(EventRow.idempotency_key == "must-rollback")
        )
    assert rolled_back == 0
    await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_ingestion_rejects_session_sequence_collision(
    app_database_url: str,
) -> None:
    engine = create_engine(app_database_url)
    sessions = create_session_factory(engine)
    ids = id_source(300)
    async with session_for_principal(sessions, principal()) as session:
        repository = PostgresEventIngestionRepository(
            session, new_id=lambda: next(ids), now=lambda: NOW
        )
        await repository.ingest_batch(
            TENANT_ID, USER_ID, (draft(key="sequence-owner", sequence=10),)
        )

    with pytest.raises(EventSequenceConflict):
        async with session_for_principal(sessions, principal()) as session:
            repository = PostgresEventIngestionRepository(
                session, new_id=lambda: next(ids), now=lambda: NOW
            )
            await repository.ingest_batch(
                TENANT_ID, USER_ID, (draft(key="sequence-attacker", sequence=10),)
            )
    await engine.dispose()
