"""C4: interactive writes must not wait behind a bulk backlog on the same queue.

The claim query is the whole contract: priority only reorders jobs that are already runnable, so
these tests also pin that a low-priority job still runs when nothing higher is waiting.
"""
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import create_engine as create_sync_engine
from sqlalchemy import select, text

from agent_memory.domain.enums import MemoryStatus, MemoryType, ScopeKind
from agent_memory.domain.events import EventDraft, EventType
from agent_memory.domain.jobs import JobPriority
from agent_memory.domain.models import Memory, MemoryScope
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
from agent_memory.infrastructure.orm import JobRow
from agent_memory.infrastructure.repositories import PostgresMemoryRepository


def principal(tenant=None):
    from agent_memory.domain.principal import RequestPrincipal

    return RequestPrincipal(
        tenant or uuid4(),
        uuid4(),
        frozenset({"developer"}),
        frozenset({"memory:write", "memory:read"}),
        frozenset({"project-a"}),
    )


def seed_job(owner_url: str, tenant, key: str, priority: int) -> None:
    engine = create_sync_engine(owner_url)
    with engine.begin() as connection:
        connection.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": str(tenant)}
        )
        connection.execute(
            text(
                "INSERT INTO jobs (tenant_id, job_id, job_type, idempotency_key, payload, status,"
                " attempts, max_attempts, priority, available_at, created_at, updated_at)"
                " VALUES (:t, :j, 'extract_event', :k, '{}', 'pending', 0, 5, :p,"
                " now() - interval '1 minute', now(), now())"
            ),
            {"t": tenant, "j": uuid4(), "k": key, "p": priority},
        )
    engine.dispose()


async def claim_keys(sessions, who, count: int) -> list[str]:
    claimed: list[str] = []
    async with session_for_principal(sessions, who) as session:
        queue = PostgresJobQueue(session)
        for index in range(count):
            job = await queue.claim(
                who.tenant_id, f"w{index}", datetime.now(UTC), timedelta(seconds=60)
            )
            if job is None:
                break
            claimed.append(job.idempotency_key)
    return claimed


async def test_interactive_job_overtakes_an_older_bulk_backlog(database_url, app_database_url):
    who = principal()
    for index in range(5):
        seed_job(database_url, who.tenant_id, f"bulk-{index}", int(JobPriority.BULK))
    seed_job(database_url, who.tenant_id, "interactive", int(JobPriority.INTERACTIVE))

    engine = create_engine(app_database_url)
    sessions = create_session_factory(engine)
    try:
        # Every job is runnable; only the order changes.
        assert await claim_keys(sessions, who, 6) == [
            "interactive",
            "bulk-0",
            "bulk-1",
            "bulk-2",
            "bulk-3",
            "bulk-4",
        ]
    finally:
        await engine.dispose()


async def test_equal_priority_still_drains_first_in_first_out(database_url, app_database_url):
    who = principal()
    for index in range(3):
        seed_job(database_url, who.tenant_id, f"same-{index}", int(JobPriority.BULK))

    engine = create_engine(app_database_url)
    sessions = create_session_factory(engine)
    try:
        assert await claim_keys(sessions, who, 3) == ["same-0", "same-1", "same-2"]
    finally:
        await engine.dispose()


async def test_ingested_batch_carries_its_priority_into_the_job(app_database_url):
    engine = create_engine(app_database_url)
    sessions = create_session_factory(engine)
    who = principal(tenant=uuid4())
    try:
        async with session_for_principal(sessions, who) as session:
            repository = PostgresEventIngestionRepository(
                session, new_id=uuid4, now=lambda: datetime.now(UTC)
            )
            await repository.ingest_batch(
                who.tenant_id,
                who.user_id,
                (event_draft("bulk-event"),),
                priority=int(JobPriority.BULK),
            )
            await repository.ingest_batch(
                who.tenant_id,
                who.user_id,
                (event_draft("interactive-event"),),
                priority=int(JobPriority.INTERACTIVE),
            )
        async with session_for_principal(sessions, who) as session:
            await PostgresOutboxRepository(
                session, new_id=uuid4, now=lambda: datetime.now(UTC)
            ).dispatch_once(who.tenant_id, 10, "v1")
        async with session_for_principal(sessions, who) as session:
            rows = (
                await session.execute(
                    select(JobRow.payload, JobRow.priority).order_by(JobRow.created_at)
                )
            ).all()
        by_event = {str(payload["event_id"]): priority for payload, priority in rows}
        assert sorted(by_event.values()) == [
            int(JobPriority.BULK),
            int(JobPriority.INTERACTIVE),
        ], "each event keeps the priority its batch was ingested with"
    finally:
        await engine.dispose()


async def test_embedding_job_inherits_the_transaction_priority(app_database_url):
    """The version trigger cannot see the extract job, so the priority travels in a GUC."""
    engine = create_engine(app_database_url)
    sessions = create_session_factory(engine)
    who = principal(tenant=uuid4())
    try:
        async with session_for_principal(sessions, who) as session:
            await session.execute(
                text("SELECT set_config('app.job_priority', :p, true)"),
                {"p": str(int(JobPriority.INTERACTIVE))},
            )
            await add_memory(session, who.tenant_id, "interactive memory")
        async with session_for_principal(sessions, who) as session:
            interactive = await embed_priorities(session)
        assert interactive == [int(JobPriority.INTERACTIVE)]

        # Without the setting the trigger falls back to the old behaviour.
        async with session_for_principal(sessions, who) as session:
            await add_memory(session, who.tenant_id, "default memory")
        async with session_for_principal(sessions, who) as session:
            defaults = await embed_priorities(session)
        assert int(JobPriority.BULK) in defaults
    finally:
        await engine.dispose()


def event_draft(key: str) -> EventDraft:
    return EventDraft(
        idempotency_key=key,
        session_id=f"s-{key}",
        sequence_number=1,
        event_type=EventType.TOOL_RESULT,
        agent_id="bench",
        occurred_at=datetime.now(UTC),
        scope=MemoryScope(ScopeKind.WORKSPACE, "project-a", None),
        payload={"tool_name": "build", "exit_code": 1, "summary": key},
    )


async def add_memory(session, tenant, content: str) -> None:
    now = datetime.now(UTC)
    memory, version = Memory.create(
        tenant_id=tenant,
        memory_id=uuid4(),
        version_id=uuid4(),
        memory_type=MemoryType.SEMANTIC,
        scope=MemoryScope(ScopeKind.TENANT, None, None),
        owner_user_id=uuid4(),
        content=content,
        now=now,
        status=MemoryStatus.ACTIVE,
    )
    await PostgresMemoryRepository(session).add(tenant, memory, version)


async def embed_priorities(session) -> list[int]:
    return list(
        (
            await session.execute(
                select(JobRow.priority).where(JobRow.job_type == "embed_memory")
            )
        ).scalars()
    )
