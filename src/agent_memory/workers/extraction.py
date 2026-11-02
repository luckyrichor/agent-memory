import argparse
import asyncio
import signal
import sys
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from types import FrameType
from uuid import UUID, uuid4

import httpx

from agent_memory.application.extraction_worker import ExtractionWorker, WorkerResult
from agent_memory.application.outbox_dispatcher import OutboxDispatcher
from agent_memory.config import Settings
from agent_memory.domain.principal import RequestPrincipal
from agent_memory.infrastructure.db import (
    create_engine,
    create_session_factory,
    session_for_principal,
)
from agent_memory.infrastructure.event_repositories import (
    PostgresExtractionBackend,
    PostgresOutboxRepository,
)
from agent_memory.infrastructure.llm_extractor import build_extractor
from agent_memory.observability import correlation, get_logger, span
from agent_memory.observability.setup import configure_observability
from agent_memory.workers.health import heartbeat
from agent_memory.workers.loop import JOBS_CHANNEL, OUTBOX_CHANNEL, Wakeup, run_loop

_logger = get_logger("agent_memory.workers.extraction")


def _bounded_integer(minimum: int, maximum: int) -> type[argparse.Action]:
    class BoundedInteger(argparse.Action):
        def __call__(
            self,
            parser: argparse.ArgumentParser,
            namespace: argparse.Namespace,
            values: str | Sequence[object] | None,
            option_string: str | None = None,
        ) -> None:
            try:
                value = int(str(values))
            except ValueError:
                parser.error(f"{option_string} must be an integer")
            if not minimum <= value <= maximum:
                parser.error(f"{option_string} must be between {minimum} and {maximum}")
            setattr(namespace, self.dest, value)

    return BoundedInteger


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Agent Memory extraction workers")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_common_arguments(command: argparse.ArgumentParser) -> None:
        command.add_argument("--tenant-id", required=True, type=UUID)
        command.add_argument("--once", action="store_true")
        command.add_argument(
            "--poll-seconds",
            default=2,
            action=_bounded_integer(1, 60),
            help="fallback poll interval; with notifications on it only bounds a missed wake-up",
        )
        command.add_argument(
            "--no-notify",
            action="store_true",
            help="disable LISTEN/NOTIFY wake-up and rely on polling only",
        )

    dispatch = subparsers.add_parser("dispatch", help="move outbox events to jobs")
    add_common_arguments(dispatch)
    dispatch.add_argument(
        "--batch-size",
        default=10,
        action=_bounded_integer(1, 100),
    )

    for name in ("work", "drain"):
        work = subparsers.add_parser(
            name, help="extract jobs; drain stops after runnable queue empties"
        )
        add_common_arguments(work)
        work.add_argument("--worker-id", required=True)
        work.add_argument(
            "--concurrency",
            default=1,
            action=_bounded_integer(1, 16),
            help="parallel claim loops in this process (FOR UPDATE SKIP LOCKED keeps them disjoint)",
        )

    return parser.parse_args(argv)


def format_worker_result(result: WorkerResult) -> str:
    job_id = str(result.job_id) if result.job_id is not None else "none"
    return f"work:job_id={job_id} outcome={result.outcome} reason_code={result.reason_code}"


def _internal_principal(tenant_id: UUID, role: str, permission: str) -> RequestPrincipal:
    return RequestPrincipal(
        tenant_id=tenant_id,
        user_id=UUID(int=0),
        roles=frozenset({role}),
        permissions=frozenset({permission}),
        allowed_workspace_ids=frozenset(),
    )


async def _pause(stop: asyncio.Event, seconds: int) -> None:
    sleep = asyncio.create_task(asyncio.sleep(seconds))
    stopping = asyncio.create_task(stop.wait())
    done, pending = await asyncio.wait(
        {sleep, stopping},
        return_when=asyncio.FIRST_COMPLETED,
    )
    for task in pending:
        task.cancel()
    await asyncio.gather(*done, *pending, return_exceptions=True)


def _install_signal_handlers(stop: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()

    def request_stop(_signum: int | None = None, _frame: FrameType | None = None) -> None:
        stop.set()

    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signum, request_stop)
        except NotImplementedError:
            signal.signal(signum, request_stop)


async def _run_dispatch(args: argparse.Namespace, stop: asyncio.Event) -> None:
    settings = Settings()
    configure_observability(settings)
    engine = create_engine(settings.database_url)
    sessions = create_session_factory(engine)
    extractor = build_extractor(settings)
    principal = _internal_principal(
        args.tenant_id,
        "outbox_dispatcher",
        "queue:dispatch",
    )
    wakeup = None if args.no_notify or args.once else Wakeup(
        settings.database_url, OUTBOX_CHANNEL, args.tenant_id
    )
    if wakeup is not None:
        wakeup.start()

    async def step() -> bool:
        with (
            correlation(request_id=str(uuid4()), tenant_id=args.tenant_id),
            span(
                "outbox.dispatch",
                action="outbox.dispatch",
                tenant_id=args.tenant_id,
                batch_size=args.batch_size,
            ),
        ):
            async with session_for_principal(sessions, principal) as session:
                repository = PostgresOutboxRepository(
                    session,
                    new_id=uuid4,
                    now=lambda: datetime.now(UTC),
                )
                count = await OutboxDispatcher(
                    repository,
                    extractor.version,
                ).dispatch_once(args.tenant_id, args.batch_size)
        reason_code = "OUTBOX_DISPATCHED" if count else "NO_PENDING_OUTBOX"
        _logger.event(
            "outbox.dispatched",
            tenant_id=args.tenant_id,
            count=count,
            reason_code=reason_code,
        )
        heartbeat(args.tenant_id, "dispatch", "dispatch", reason_code)
        print(f"dispatch:count={count} reason_code={reason_code}")
        return count > 0

    try:
        await run_loop(
            stop, step, poll_seconds=args.poll_seconds, wakeup=wakeup, once=args.once
        )
    finally:
        if wakeup is not None:
            await wakeup.aclose()
        await engine.dispose()


async def _run_worker(args: argparse.Namespace, stop: asyncio.Event) -> None:
    settings = Settings()
    configure_observability(settings)
    engine = create_engine(settings.database_url)
    sessions = create_session_factory(engine)
    http = httpx.AsyncClient(
        timeout=settings.extraction_timeout_seconds,
        trust_env=settings.extraction_trust_env,
        limits=httpx.Limits(max_connections=8, max_keepalive_connections=4),
    )
    wakeup = None if args.no_notify or args.once else Wakeup(
        settings.database_url, JOBS_CHANNEL, args.tenant_id
    )
    if wakeup is not None:
        wakeup.start()

    def build_worker() -> tuple[ExtractionWorker, str]:
        # One extractor per loop: LLMExtractor keeps per-call state (last_reason / last_failure)
        # that concurrent loops must not share.
        extractor = build_extractor(settings, http)
        return (
            ExtractionWorker(
                PostgresExtractionBackend(
                    sessions,
                    new_id=uuid4,
                    now=lambda: datetime.now(UTC),
                    extractor_version=extractor.version,
                    activation=settings.candidate_activation,
                ),
                extractor,
                now=lambda: datetime.now(UTC),
                lease_duration=timedelta(seconds=settings.worker_lease_seconds),
            ),
            extractor.version,
        )

    concurrency = getattr(args, "concurrency", 1)

    async def loop(index: int) -> None:
        worker, version = build_worker()
        worker_id = args.worker_id if concurrency == 1 else f"{args.worker_id}-{index}"

        async def step() -> bool:
            with correlation(request_id=str(uuid4()), tenant_id=args.tenant_id):
                result = await worker.run_once(args.tenant_id, worker_id)
            heartbeat(args.tenant_id, worker_id, "extraction", result.reason_code)
            print(format_worker_result(result))
            if result.outcome != "no_job":
                return True
            if args.command == "drain" and not args.once:
                from agent_memory.infrastructure.queue_admin import PostgresQueueAdmin

                status = await PostgresQueueAdmin(sessions, args.tenant_id).status(
                    job_type="extract_event", version=version
                )
                counts = status["counts"]
                if isinstance(counts, dict) and not any(
                    counts.get(k, 0) for k in ("pending", "retry_wait", "running")
                ):
                    print(f"drain: outcome=finished dead_count={counts.get('dead', 0)}")
                    stop.set()
            return False

        await run_loop(
            stop, step, poll_seconds=args.poll_seconds, wakeup=wakeup, once=args.once
        )

    try:
        await asyncio.gather(*(loop(i) for i in range(concurrency)))
    finally:
        if wakeup is not None:
            await wakeup.aclose()
        await http.aclose()
        await engine.dispose()


async def run(args: argparse.Namespace) -> None:
    stop = asyncio.Event()
    _install_signal_handlers(stop)
    if args.command == "dispatch":
        await _run_dispatch(args, stop)
    else:
        await _run_worker(args, stop)


def main(argv: Sequence[str] | None = None) -> int:
    asyncio.run(run(parse_args(argv)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
