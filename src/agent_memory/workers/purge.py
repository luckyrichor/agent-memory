"""Physical clean-up of logically deleted memories (see ``infrastructure/purge.py``).

Dry run unless ``--execute`` is given. Output is counts only: no ids, no text.

    python -m agent_memory.workers.purge --tenant-id <uuid> --older-than-days 30
    python -m agent_memory.workers.purge --tenant-id <uuid> --older-than-days 30 --execute
"""

import argparse
import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from agent_memory.config import Settings
from agent_memory.infrastructure.db import create_engine, create_session_factory
from agent_memory.infrastructure.purge import purge_deleted_memories
from agent_memory.observability.setup import configure_observability
from agent_memory.workers.extraction import _bounded_integer

DRY_RUN_LIMIT = 100_000  # a dry run writes nothing, so it can count far more than one batch


async def run(args: argparse.Namespace) -> None:
    settings = Settings()
    configure_observability(settings)
    engine = create_engine(settings.database_url)
    sessions = create_session_factory(engine)
    try:
        total = [0, 0, 0, 0]
        while True:
            report = await purge_deleted_memories(
                sessions,
                args.tenant_id,
                older_than=timedelta(days=args.older_than_days),
                now=datetime.now(UTC),
                new_id=uuid4,
                execute=args.execute,
                limit=args.batch_size if args.execute else DRY_RUN_LIMIT,
            )
            for index, value in enumerate(
                (report.memories, report.versions, report.embeddings, report.jobs_stopped)
            ):
                total[index] += value
            # A dry run changes nothing, so a second batch would just repeat the first.
            if not args.execute or report.memories == 0:
                break
        print(
            f"purge: mode={'execute' if args.execute else 'dry-run'} memories={total[0]} "
            f"versions={total[1]} embeddings={total[2]} jobs_stopped={total[3]}"
        )
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Erase text and vectors of logically deleted memories (dry run by default)"
    )
    parser.add_argument("--tenant-id", type=UUID, required=True)
    parser.add_argument(
        "--older-than-days",
        required=True,
        action=_bounded_integer(0, 3650),
        help="only memories deleted at least this long ago; no default on purpose",
    )
    parser.add_argument("--batch-size", default=500, action=_bounded_integer(1, 5000))
    parser.add_argument("--execute", action="store_true", help="actually erase; default is a dry run")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
