import asyncio
import itertools
import time

import pytest

from agent_memory.workers.loop import Wakeup, pause, run_loop


@pytest.mark.asyncio
async def test_loop_does_not_sleep_while_there_is_work() -> None:
    """Old behaviour slept poll_seconds after every job, so N jobs took N * poll_seconds."""
    stop = asyncio.Event()
    queue = list(range(50))

    async def step() -> bool:
        if not queue:
            stop.set()
            return False
        queue.pop()
        return True

    started = time.monotonic()
    await run_loop(stop, step, poll_seconds=5)
    assert not queue
    assert time.monotonic() - started < 1.0  # 50 jobs with a 5 s poll would take 250 s before


@pytest.mark.asyncio
async def test_loop_waits_poll_interval_only_when_idle() -> None:
    stop = asyncio.Event()
    calls: list[float] = []

    async def step() -> bool:
        calls.append(time.monotonic())
        if len(calls) == 3:
            stop.set()
        return False

    await run_loop(stop, step, poll_seconds=0.05)
    gaps = [b - a for a, b in itertools.pairwise(calls)]
    assert all(gap >= 0.04 for gap in gaps)


@pytest.mark.asyncio
async def test_once_runs_exactly_one_step() -> None:
    stop = asyncio.Event()
    count = 0

    async def step() -> bool:
        nonlocal count
        count += 1
        return True

    await run_loop(stop, step, poll_seconds=1, once=True)
    assert count == 1


@pytest.mark.asyncio
async def test_stop_interrupts_an_idle_wait_immediately() -> None:
    stop = asyncio.Event()

    async def step() -> bool:
        return False

    task = asyncio.create_task(run_loop(stop, step, poll_seconds=60))
    await asyncio.sleep(0.05)
    started = time.monotonic()
    stop.set()
    await asyncio.wait_for(task, timeout=2)
    assert time.monotonic() - started < 1.0


@pytest.mark.asyncio
async def test_notification_during_a_step_is_not_lost() -> None:
    """Token is read before the step, so a wake-up that races the step ends the next wait at once."""
    wakeup = Wakeup("postgresql+psycopg_async://u:p@127.0.0.1:1/x", "agent_memory_jobs",
                    __import__("uuid").uuid4())
    stop = asyncio.Event()
    token = wakeup.token()
    wakeup._bump()  # notification arrives while the step is still running
    started = time.monotonic()
    assert await wakeup.wait(token, 30, stop) == "notified"
    assert time.monotonic() - started < 0.5


@pytest.mark.asyncio
async def test_pause_returns_early_on_stop() -> None:
    stop = asyncio.Event()
    asyncio.get_running_loop().call_later(0.05, stop.set)
    started = time.monotonic()
    await pause(stop, 30)
    assert time.monotonic() - started < 1.0
