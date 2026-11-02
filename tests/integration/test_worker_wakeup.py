"""LISTEN/NOTIFY wake-up against a real PostgreSQL (migration 0009)."""
import asyncio
import time
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, text

from agent_memory.workers.loop import JOBS_CHANNEL, OUTBOX_CHANNEL, Wakeup, tenant_digest


@pytest.fixture
def migrated_url(database_url: str, app_database_url: str) -> str:
    """Owner URL of a database that has been migrated to head (app_database_url upgrades it)."""
    return database_url


def async_url(database_url: str) -> str:
    return database_url.replace("postgresql+psycopg://", "postgresql+psycopg_async://")


def insert_job(database_url: str, tenant: UUID) -> None:
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": str(tenant)}
        )
        connection.execute(
            text(
                "INSERT INTO jobs (tenant_id, job_id, job_type, idempotency_key, payload, status,"
                " attempts, max_attempts, available_at, created_at, updated_at)"
                " VALUES (:t, :j, 'embed_memory', :k, '{}', 'pending', 0, 5, now(), now(), now())"
            ),
            {"t": tenant, "j": uuid4(), "k": str(uuid4())},
        )
    engine.dispose()


async def connected(wakeup: Wakeup) -> None:
    for _ in range(100):
        if wakeup.connected:
            return
        await asyncio.sleep(0.05)
    raise AssertionError("LISTEN connection did not come up")


@pytest.mark.asyncio
async def test_new_job_wakes_the_waiting_worker_long_before_the_poll_timeout(
    migrated_url: str,
) -> None:
    database_url = migrated_url
    tenant = uuid4()
    wakeup = Wakeup(async_url(database_url), JOBS_CHANNEL, tenant)
    wakeup.start()
    await connected(wakeup)
    stop = asyncio.Event()
    token = wakeup.token()
    started = time.monotonic()
    asyncio.get_running_loop().call_later(
        0.3, lambda: asyncio.get_running_loop().run_in_executor(None, insert_job, database_url, tenant)
    )
    result = await wakeup.wait(token, 30, stop)
    elapsed = time.monotonic() - started
    await wakeup.aclose()
    assert result == "notified"
    assert elapsed < 3.0, elapsed  # poll fallback was 30 s


@pytest.mark.asyncio
async def test_other_tenants_jobs_do_not_wake_this_worker(migrated_url: str) -> None:
    database_url = migrated_url
    mine, other = uuid4(), uuid4()
    wakeup = Wakeup(async_url(database_url), JOBS_CHANNEL, mine)
    wakeup.start()
    await connected(wakeup)
    stop = asyncio.Event()
    token = wakeup.token()
    await asyncio.get_running_loop().run_in_executor(None, insert_job, database_url, other)
    assert await wakeup.wait(token, 1.0, stop) == "timeout"
    await wakeup.aclose()


@pytest.mark.asyncio
async def test_unreachable_database_degrades_to_polling_not_a_crash() -> None:
    wakeup = Wakeup(
        "postgresql+psycopg_async://u:p@127.0.0.1:1/none", OUTBOX_CHANNEL, uuid4()
    )
    wakeup.start()
    stop = asyncio.Event()
    result = await wakeup.wait(wakeup.token(), 0.3, stop)
    await wakeup.aclose()
    assert result == "timeout" and not wakeup.connected


def test_payload_is_digest_of_tenant_never_the_tenant_id(migrated_url: str) -> None:
    database_url = migrated_url
    tenant = uuid4()
    engine = create_engine(database_url)
    with engine.connect() as connection:
        expected = connection.execute(text("SELECT md5(:t)"), {"t": str(tenant)}).scalar()
    engine.dispose()
    assert tenant_digest(tenant) == expected
    assert str(tenant) not in tenant_digest(tenant)
