"""Shared worker loop: no sleeping while there is work, wake-up on NOTIFY, polling as fallback.

Three defects of the old per-worker loops (measured in docs/optimization/measurements):
  1. they slept ``poll_seconds`` after EVERY job, so a backlog of N jobs took N * poll_seconds;
  2. a new job waited up to ``poll_seconds`` before anyone looked at it, and the dispatch ->
     extraction -> embedding chain stacks that wait once per hop;
  3. one job at a time per process.

Fix: (1) only wait when the last step found nothing; (2) block on a PostgreSQL LISTEN channel and
wake the moment a trigger notifies; keep the poll timeout as a safety net (notifications are
best-effort: lost on disconnect, duplicated is harmless); (3) callers may run several loops.

Correctness never depends on a notification: the claim query alone decides what is runnable.
"""
import asyncio
import hashlib
from collections.abc import Awaitable, Callable
from uuid import UUID

import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url

JOBS_CHANNEL = "agent_memory_jobs"
OUTBOX_CHANNEL = "agent_memory_outbox"


def tenant_digest(tenant_id: UUID) -> str:
    """Same value the trigger sends: md5(tenant_id::text). Not a security boundary."""
    return hashlib.md5(str(tenant_id).encode(), usedforsecurity=False).hexdigest()


def listen_url(database_url: str) -> str:
    """SQLAlchemy async URL -> plain libpq URL for a dedicated LISTEN connection."""
    return make_url(database_url).set(drivername="postgresql").render_as_string(hide_password=False)


class Wakeup:
    """One LISTEN connection per process; wakes every waiting loop of this tenant."""

    def __init__(self, database_url: str, channel: str, tenant_id: UUID) -> None:
        self._url = listen_url(database_url)
        self._channel = channel
        self._digest = tenant_digest(tenant_id)
        self._generation = 0
        self._waiters: set[asyncio.Event] = set()
        self._task: asyncio.Task[None] | None = None
        self.connected = False
        self.notifications = 0

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._listen())

    async def aclose(self) -> None:
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None

    def token(self) -> int:
        """Read BEFORE doing a step; a notification arriving during the step is not lost."""
        return self._generation

    def _bump(self) -> None:
        self._generation += 1
        for waiter in self._waiters:
            waiter.set()

    async def wait(self, token: int, timeout: float, stop: asyncio.Event) -> str:
        if self._generation != token:
            return "notified"
        if stop.is_set():
            return "stopped"
        event = asyncio.Event()
        self._waiters.add(event)
        stopping = asyncio.create_task(stop.wait())
        waiting = asyncio.create_task(event.wait())
        try:
            done, _ = await asyncio.wait(
                {stopping, waiting}, timeout=timeout, return_when=asyncio.FIRST_COMPLETED
            )
        finally:
            self._waiters.discard(event)
            for task in (stopping, waiting):
                task.cancel()
            await asyncio.gather(stopping, waiting, return_exceptions=True)
        if stopping in done:
            return "stopped"
        return "notified" if waiting in done else "timeout"

    async def _listen(self) -> None:
        delay = 1.0
        while True:
            try:
                async with await psycopg.AsyncConnection.connect(
                    self._url, autocommit=True
                ) as connection:
                    await connection.execute(
                        sql.SQL("LISTEN {}").format(sql.Identifier(self._channel))
                    )
                    self.connected = True
                    delay = 1.0
                    self._bump()  # anything missed while (re)connecting is picked up now
                    async for notice in connection.notifies():
                        if notice.payload == self._digest:
                            self.notifications += 1
                            self._bump()
            except asyncio.CancelledError:
                self.connected = False
                raise
            except Exception:  # noqa: BLE001 - never crash a worker over a wake-up channel
                self.connected = False
            await asyncio.sleep(delay)
            delay = min(delay * 2, 15.0)


async def pause(stop: asyncio.Event, seconds: float) -> None:
    try:
        await asyncio.wait_for(stop.wait(), timeout=seconds)
    except TimeoutError:
        pass


async def run_loop(
    stop: asyncio.Event,
    step: Callable[[], Awaitable[bool]],
    *,
    poll_seconds: float,
    wakeup: Wakeup | None = None,
    once: bool = False,
) -> None:
    """Run ``step`` until stopped. ``step`` returns True if it did work (then loop at once)."""
    while not stop.is_set():
        token = wakeup.token() if wakeup is not None else 0
        worked = await step()
        if once:
            return
        if worked:
            continue
        if wakeup is not None:
            await wakeup.wait(token, poll_seconds, stop)
        else:
            await pause(stop, poll_seconds)
