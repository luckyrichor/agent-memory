import argparse
import asyncio
from datetime import UTC, datetime
from uuid import UUID

import httpx

from agent_memory.application.embedding import EmbeddingProvider, EmbeddingWorker
from agent_memory.config import Settings
from agent_memory.infrastructure.db import create_engine, create_session_factory
from agent_memory.infrastructure.embedding import (
    FixtureEmbeddingProvider,
    HTTPEmbeddingProvider,
    PostgresEmbeddingBackend,
)
from agent_memory.observability.setup import configure_observability
from agent_memory.workers.extraction import _bounded_integer, _install_signal_handlers
from agent_memory.workers.health import heartbeat
from agent_memory.workers.loop import JOBS_CHANNEL, Wakeup, run_loop


async def run(args: argparse.Namespace) -> None:
    stop = asyncio.Event()
    _install_signal_handlers(stop)
    settings = Settings()
    configure_observability(settings)
    engine = create_engine(settings.database_url)
    backend = PostgresEmbeddingBackend(create_session_factory(engine))
    try:
        if args.command == "rebuild":
            await backend.rebuild(args.tenant_id, args.version_id, args.key, datetime.now(UTC))
            print("rebuild: outcome=queued")
            return
        async with httpx.AsyncClient(
            timeout=settings.embedding_timeout_seconds, trust_env=settings.embedding_trust_env
        ) as http:
            provider: EmbeddingProvider
            if args.fixture:
                provider = FixtureEmbeddingProvider(args.fixture_latency_ms / 1000)
            else:
                # No credentials are printed; missing configuration fails closed.
                if not settings.embedding_endpoint or not settings.embedding_model:
                    raise ValueError("embedding endpoint and model must be configured")
                provider = HTTPEmbeddingProvider(
                    http,
                    endpoint=settings.embedding_endpoint,
                    model=settings.embedding_model,
                    token=settings.embedding_token.get_secret_value(),
                    protocol=settings.embedding_protocol,
                )
            worker = EmbeddingWorker(
                backend,
                provider,
                timeout=settings.embedding_timeout_seconds,
                lease_seconds=settings.worker_lease_seconds,
            )
            wakeup = None if args.no_notify or args.once else Wakeup(
                settings.database_url, JOBS_CHANNEL, args.tenant_id
            )
            if wakeup is not None:
                wakeup.start()

            async def loop(index: int) -> None:
                worker_id = args.worker_id if args.concurrency == 1 else f"{args.worker_id}-{index}"

                async def step() -> bool:
                    result = await worker.run_once(args.tenant_id, worker_id)
                    heartbeat(args.tenant_id, worker_id, "embedding", result.reason_code)
                    print(
                        f"embedding: job_id={result.job_id} outcome={result.outcome} "
                        f"reason_code={result.reason_code}"
                    )
                    return result.outcome != "no_job"

                await run_loop(
                    stop, step, poll_seconds=args.poll_seconds, wakeup=wakeup, once=args.once
                )

            try:
                await asyncio.gather(*(loop(i) for i in range(args.concurrency)))
            finally:
                if wakeup is not None:
                    await wakeup.aclose()
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Durable embedding worker")
    sub = parser.add_subparsers(dest="command", required=True)
    work = sub.add_parser("work")
    work.add_argument("--worker-id", required=True)
    work.add_argument("--once", action="store_true")
    work.add_argument("--poll-seconds", default=2, action=_bounded_integer(1, 60))
    work.add_argument("--no-notify", action="store_true")
    work.add_argument(
        "--fixture-latency-ms", type=int, default=0, help="with --fixture: simulated provider delay"
    )
    work.add_argument("--concurrency", default=1, action=_bounded_integer(1, 16))
    work.add_argument(
        "--fixture", action="store_true", help="pipeline test only, no semantic model"
    )
    rebuild = sub.add_parser("rebuild")
    rebuild.add_argument("--version-id", type=UUID, required=True)
    rebuild.add_argument("--key", required=True)
    for command in (work, rebuild):
        command.add_argument("--tenant-id", type=UUID, required=True)
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
