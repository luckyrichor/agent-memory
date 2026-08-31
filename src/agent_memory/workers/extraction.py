import argparse
import asyncio
import signal
import sys
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from types import FrameType
from uuid import UUID, uuid4

from agent_memory.application.extraction import CodingFailureRuleExtractor
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
                parser.error(
                    f"{option_string} must be between {minimum} and {maximum}"
                )
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
        )

    dispatch = subparsers.add_parser("dispatch", help="move outbox events to jobs")
    add_common_arguments(dispatch)
    dispatch.add_argument(
        "--batch-size",
        default=10,
        action=_bounded_integer(1, 100),
    )

    work = subparsers.add_parser("work", help="extract memory candidates from jobs")
    add_common_arguments(work)
    work.add_argument("--worker-id", required=True)

    return parser.parse_args(argv)


def format_worker_result(result: WorkerResult) -> str:
    job_id = str(result.job_id) if result.job_id is not None else "none"
    return (
        f"work:job_id={job_id} outcome={result.outcome} "
        f"reason_code={result.reason_code}"
    )


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
    engine = create_engine(settings.database_url)
    sessions = create_session_factory(engine)
    extractor = CodingFailureRuleExtractor()
    principal = _internal_principal(
        args.tenant_id,
        "outbox_dispatcher",
        "queue:dispatch",
    )
    try:
        while not stop.is_set():
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
            print(f"dispatch:count={count} reason_code={reason_code}")
            if args.once:
                break
            await _pause(stop, args.poll_seconds)
    finally:
        await engine.dispose()


async def _run_worker(args: argparse.Namespace, stop: asyncio.Event) -> None:
    settings = Settings()
    engine = create_engine(settings.database_url)
    sessions = create_session_factory(engine)
    worker = ExtractionWorker(
        PostgresExtractionBackend(
            sessions,
            new_id=uuid4,
            now=lambda: datetime.now(UTC),
        ),
        CodingFailureRuleExtractor(),
        now=lambda: datetime.now(UTC),
        lease_duration=timedelta(seconds=30),
    )
    try:
        while not stop.is_set():
            result = await worker.run_once(args.tenant_id, args.worker_id)
            print(format_worker_result(result))
            if args.once:
                break
            await _pause(stop, args.poll_seconds)
    finally:
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
