import argparse
import asyncio
import os
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


async def run(args: argparse.Namespace) -> None:
    settings = Settings()
    configure_observability(settings)
    engine = create_engine(settings.database_url)
    backend = PostgresEmbeddingBackend(create_session_factory(engine))
    try:
        if args.command == "rebuild":
            await backend.rebuild(args.tenant_id, args.version_id, args.key, datetime.now(UTC))
            print("rebuild: outcome=queued")
            return
        async with httpx.AsyncClient(timeout=10) as http:
            provider: EmbeddingProvider
            if args.fixture:
                provider = FixtureEmbeddingProvider()
            else:
                # No credentials are printed; missing configuration fails closed.
                provider = HTTPEmbeddingProvider(http, endpoint=os.environ["MEMORY_EMBEDDING_URL"],
                    model=os.environ["MEMORY_EMBEDDING_MODEL"],
                    token=os.environ["MEMORY_EMBEDDING_TOKEN"])
            worker = EmbeddingWorker(backend, provider)
            while True:
                result = await worker.run_once(args.tenant_id, args.worker_id)
                print(f"embedding: job_id={result.job_id} outcome={result.outcome} "
                      f"reason_code={result.reason_code}")
                if args.once:
                    break
                await asyncio.sleep(2)
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Durable embedding worker")
    sub = parser.add_subparsers(dest="command", required=True)
    work = sub.add_parser("work")
    work.add_argument("--worker-id", required=True)
    work.add_argument("--once", action="store_true")
    work.add_argument("--fixture", action="store_true", help="pipeline test only, no semantic model")
    rebuild = sub.add_parser("rebuild")
    rebuild.add_argument("--version-id", type=UUID, required=True)
    rebuild.add_argument("--key", required=True)
    for command in (work, rebuild):
        command.add_argument("--tenant-id", type=UUID, required=True)
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
