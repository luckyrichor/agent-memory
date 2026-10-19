from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text, update

from agent_memory.domain.errors import LeaseLost
from agent_memory.domain.principal import RequestPrincipal
from agent_memory.infrastructure.db import (
    create_engine,
    create_session_factory,
    database_now,
    session_for_principal,
)
from agent_memory.infrastructure.event_repositories import PostgresJobQueue
from agent_memory.infrastructure.orm import JobRow


async def test_queue_ignores_fast_and_slow_worker_clocks(app_database_url):
    engine = create_engine(app_database_url)
    sessions = create_session_factory(engine)
    tenant, jid = uuid4(), uuid4()
    principal = RequestPrincipal(tenant, uuid4(), frozenset(), frozenset(), frozenset())
    past = datetime(2000, 1, 1, tzinfo=UTC)
    future = datetime(2100, 1, 1, tzinfo=UTC)
    try:
        async with session_for_principal(sessions, principal) as session:
            at = await database_now(session)
            session.add(JobRow(tenant_id=tenant, job_id=jid, job_type='extract_event',
                idempotency_key='clock', payload={}, status='pending', attempts=0, max_attempts=5,
                available_at=at+timedelta(days=1), created_at=at, updated_at=at))
        async with session_for_principal(sessions, principal) as session:
            assert await PostgresJobQueue(session).claim(tenant,'fast',future,timedelta(seconds=30)) is None
            await session.execute(update(JobRow).where(JobRow.job_id==jid).values(
                available_at=func.clock_timestamp()-text("interval '1 second'")))
        async with session_for_principal(sessions, principal) as session:
            job = await PostgresJobQueue(session).claim(tenant,'owner',past,timedelta(seconds=30))
            assert job is not None and job.updated_at > past+timedelta(days=1)
            assert job.leased_until == job.updated_at+timedelta(seconds=30)
        async with session_for_principal(sessions, principal) as session:
            assert await PostgresJobQueue(session).claim(tenant,'fast',future,timedelta(seconds=30)) is None
            await session.execute(update(JobRow).where(JobRow.job_id==jid).values(
                leased_until=func.clock_timestamp()-text("interval '1 second'")))
        for action in ('renew','succeed','fail'):
            with pytest.raises(LeaseLost):
                async with session_for_principal(sessions, principal) as session:
                    queue = PostgresJobQueue(session)
                    if action == 'renew':
                        await queue.renew(tenant,jid,'owner',past,timedelta(seconds=30))
                    elif action == 'succeed':
                        await queue.succeed(tenant,jid,'owner',past)
                    else:
                        await queue.fail(tenant,jid,'owner',past,'FIXTURE',retryable=True)
        async with session_for_principal(sessions, principal) as session:
            recovered = await PostgresJobQueue(session).claim(tenant,'recovered',past,timedelta(seconds=30))
            assert recovered is not None and recovered.attempts == 2
        with pytest.raises(LeaseLost):
            async with session_for_principal(sessions, principal) as session:
                await PostgresJobQueue(session).succeed(tenant,jid,'owner',past)
    finally:
        await engine.dispose()


async def test_lease_expiry_uses_wall_clock_not_transaction_start(app_database_url):
    engine = create_engine(app_database_url)
    sessions = create_session_factory(engine)
    tenant, jid = uuid4(), uuid4()
    principal = RequestPrincipal(tenant, uuid4(), frozenset(), frozenset(), frozenset())
    try:
        async with session_for_principal(sessions, principal) as session:
            at = await database_now(session)
            session.add(JobRow(tenant_id=tenant, job_id=jid, job_type='extract_event',
                idempotency_key='wall-clock', payload={}, status='running', attempts=1,max_attempts=5,
                available_at=at, leased_until=at+timedelta(seconds=10), lease_owner='owner',
                created_at=at, updated_at=at))
        with pytest.raises(LeaseLost):
            async with session_for_principal(sessions, principal) as session:
                start = await session.scalar(select(func.now()))
                await session.execute(update(JobRow).where(JobRow.job_id==jid).values(
                    leased_until=func.clock_timestamp()+text("interval '30 milliseconds'")))
                await session.execute(text('SELECT pg_sleep(0.06)'))
                await PostgresJobQueue(session).succeed(tenant,jid,'owner',start)
    finally:
        await engine.dispose()
