"""Several claim loops in one process must take disjoint jobs (FOR UPDATE SKIP LOCKED)."""
import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine as create_sync_engine
from sqlalchemy import text

from agent_memory.domain.principal import RequestPrincipal
from agent_memory.infrastructure.db import (
    create_engine,
    create_session_factory,
    session_for_principal,
)
from agent_memory.infrastructure.event_repositories import PostgresJobQueue
from agent_memory.workers.loop import run_loop

JOBS = 24
LOOPS = 4


def seed_jobs(owner_url: str, tenant, count: int) -> None:
    engine = create_sync_engine(owner_url)
    with engine.begin() as connection:
        connection.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": str(tenant)}
        )
        for _ in range(count):
            connection.execute(
                text(
                    "INSERT INTO jobs (tenant_id, job_id, job_type, idempotency_key, payload,"
                    " status, attempts, max_attempts, available_at, created_at, updated_at)"
                    " VALUES (:t, :j, 'extract_event', :k, '{}', 'pending', 0, 5,"
                    " now() - interval '1 minute', now(), now())"
                ),
                {"t": tenant, "j": uuid4(), "k": str(uuid4())},
            )
    engine.dispose()


@pytest.mark.asyncio
async def test_parallel_loops_claim_every_job_exactly_once(
    database_url: str, app_database_url: str
) -> None:
    tenant = uuid4()
    seed_jobs(database_url, tenant, JOBS)
    engine = create_engine(app_database_url)
    sessions = create_session_factory(engine)
    principal = RequestPrincipal(
        tenant, uuid4(), frozenset({"developer"}), frozenset({"memory:write"}), frozenset()
    )
    claimed: list[tuple[int, object]] = []
    stop = asyncio.Event()

    def make_step(loop_index: int):
        async def step() -> bool:
            async with session_for_principal(sessions, principal) as session:
                job = await PostgresJobQueue(session).claim(
                    tenant, f"loop-{loop_index}", datetime.now(UTC), timedelta(seconds=60)
                )
            if job is None:
                if len(claimed) >= JOBS:
                    stop.set()
                return False
            claimed.append((loop_index, job.job_id))
            await asyncio.sleep(0.05)  # simulated work, lets the other loops overlap
            return True

        return step

    await asyncio.wait_for(
        asyncio.gather(
            *(run_loop(stop, make_step(i), poll_seconds=0.05) for i in range(LOOPS))
        ),
        timeout=60,
    )
    await engine.dispose()

    job_ids = [job_id for _, job_id in claimed]
    assert len(job_ids) == JOBS
    assert len(set(job_ids)) == JOBS  # no job claimed twice
    # the loops really ran in parallel: more than one of them got work
    assert len({loop_index for loop_index, _ in claimed}) > 1
