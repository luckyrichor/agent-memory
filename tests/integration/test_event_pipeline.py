from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import func, select

from agent_memory.domain.enums import ScopeKind
from agent_memory.domain.errors import (
    EventIdempotencyConflict,
    EventSequenceConflict,
    LeaseLost,
)
from agent_memory.domain.events import EventDraft, EventType
from agent_memory.domain.models import MemoryScope
from agent_memory.domain.principal import RequestPrincipal
from agent_memory.infrastructure.db import (
    create_engine,
    create_session_factory,
    session_for_principal,
)
from agent_memory.infrastructure.event_repositories import (
    PostgresEventIngestionRepository,
    PostgresJobQueue,
    PostgresOutboxRepository,
)
from agent_memory.infrastructure.orm import EventRow, JobRow, OutboxMessageRow

TENANT_ID = UUID("31000000-0000-0000-0000-000000000001")
USER_ID = UUID("31000000-0000-0000-0000-000000000002")
DISPATCH_TENANT_ID = UUID("31000000-0000-0000-0000-000000000011")
LEASE_TENANT_ID = UUID("31000000-0000-0000-0000-000000000012")
NOW = datetime(2026, 8, 30, 16, 0, tzinfo=UTC)


def principal(tenant_id: UUID = TENANT_ID) -> RequestPrincipal:
    return RequestPrincipal(
        tenant_id=tenant_id,
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


@pytest.mark.asyncio
async def test_postgres_outbox_dispatch_is_idempotent(app_database_url: str) -> None:
    engine = create_engine(app_database_url)
    sessions = create_session_factory(engine)
    ids = id_source(400)
    async with session_for_principal(sessions, principal(DISPATCH_TENANT_ID)) as session:
        await PostgresEventIngestionRepository(
            session, new_id=lambda: next(ids), now=lambda: NOW
        ).ingest_batch(
            DISPATCH_TENANT_ID,
            USER_ID,
            (draft(key="dispatch-integration", sequence=20),),
        )

    async with session_for_principal(sessions, principal(DISPATCH_TENANT_ID)) as session:
        first = await PostgresOutboxRepository(
            session, new_id=lambda: next(ids), now=lambda: NOW
        ).dispatch_once(DISPATCH_TENANT_ID, 10, "coding-failure-rule-v1")
    async with session_for_principal(sessions, principal(DISPATCH_TENANT_ID)) as session:
        second = await PostgresOutboxRepository(
            session, new_id=lambda: next(ids), now=lambda: NOW
        ).dispatch_once(DISPATCH_TENANT_ID, 10, "coding-failure-rule-v1")
        jobs = await session.scalar(
            select(func.count())
            .select_from(JobRow)
            .where(JobRow.tenant_id == DISPATCH_TENANT_ID)
        )
        status_value = await session.scalar(
            select(OutboxMessageRow.status).where(
                OutboxMessageRow.tenant_id == DISPATCH_TENANT_ID,
                OutboxMessageRow.aggregate_id
                == select(EventRow.event_id)
                .where(EventRow.idempotency_key == "dispatch-integration")
                .scalar_subquery(),
            )
        )

    assert first == 1
    assert second == 0
    assert jobs == 1
    assert status_value == "published"
    await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_job_lease_blocks_steal_and_recovers_after_expiry(
    app_database_url: str,
) -> None:
    engine = create_engine(app_database_url)
    sessions = create_session_factory(engine)
    ids = id_source(500)
    async with session_for_principal(sessions, principal(LEASE_TENANT_ID)) as session:
        await PostgresEventIngestionRepository(
            session, new_id=lambda: next(ids), now=lambda: NOW
        ).ingest_batch(
            LEASE_TENANT_ID,
            USER_ID,
            (draft(key="lease-integration", sequence=21),),
        )
    async with session_for_principal(sessions, principal(LEASE_TENANT_ID)) as session:
        await PostgresOutboxRepository(
            session, new_id=lambda: next(ids), now=lambda: NOW
        ).dispatch_once(LEASE_TENANT_ID, 10, "coding-failure-rule-v1")

    async with session_for_principal(sessions, principal(LEASE_TENANT_ID)) as session:
        claimed = await PostgresJobQueue(session).claim(
            LEASE_TENANT_ID, "worker-a", NOW, timedelta(seconds=30)
        )
    assert claimed is not None
    assert claimed.attempts == 1

    async with session_for_principal(sessions, principal(LEASE_TENANT_ID)) as session:
        blocked = await PostgresJobQueue(session).claim(
            LEASE_TENANT_ID,
            "worker-b",
            NOW + timedelta(seconds=29),
            timedelta(seconds=30),
        )
    assert blocked is None

    async with session_for_principal(sessions, principal(LEASE_TENANT_ID)) as session:
        queue = PostgresJobQueue(session)
        reclaimed = await queue.claim(
            LEASE_TENANT_ID,
            "worker-b",
            NOW + timedelta(seconds=31),
            timedelta(seconds=30),
        )
        assert reclaimed is not None
        assert reclaimed.job_id == claimed.job_id
        assert reclaimed.attempts == 2
        with pytest.raises(LeaseLost):
            await queue.renew(
                LEASE_TENANT_ID,
                reclaimed.job_id,
                "worker-a",
                NOW + timedelta(seconds=32),
                timedelta(seconds=30),
            )
        renewed = await queue.renew(
            LEASE_TENANT_ID,
            reclaimed.job_id,
            "worker-b",
            NOW + timedelta(seconds=32),
            timedelta(seconds=30),
        )
        assert renewed.leased_until == NOW + timedelta(seconds=62)

    await engine.dispose()
