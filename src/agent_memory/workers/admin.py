"""Trusted-host operations CLI; database role must remain subject to RLS."""

import argparse
import asyncio
import json
from uuid import UUID

from agent_memory.application.queue_ports import QueueAdmin
from agent_memory.config import Settings
from agent_memory.infrastructure.db import create_engine, create_session_factory
from agent_memory.infrastructure.queue_admin import PostgresQueueAdmin


async def run(args: argparse.Namespace) -> None:
    settings = Settings()
    from agent_memory.observability.setup import configure_observability

    configure_observability(settings)
    engine = create_engine(settings.database_url)
    admin: QueueAdmin = PostgresQueueAdmin(create_session_factory(engine), args.tenant_id)
    try:
        if args.command == "status":
            result: object = await admin.status(job_type=args.job_type, version=args.version)
        elif args.command == "requeue":
            result = {
                "changed": await admin.requeue(
                    job_type=args.job_type,
                    limit=args.limit,
                    old_version=args.old_version,
                    new_version=args.new_version,
                )
            }
        elif args.command == "rebuild-model":
            result = {"queued": await admin.rebuild_model(args.model, args.key, limit=args.limit)}
        else:
            result = {"deleted": await admin.cleanup_idempotency(limit=args.limit)}
        print(json.dumps(result))
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("status", "requeue", "rebuild-model", "cleanup-idempotency"):
        command = sub.add_parser(name)
        command.add_argument("--tenant-id", type=UUID, required=True)
        if name == "status":
            command.add_argument("--job-type", choices=["extract_event", "embed_memory"])
            command.add_argument("--version")
        else:
            command.add_argument("--limit", type=int, default=100)
        if name == "requeue":
            command.add_argument(
                "--job-type", choices=["extract_event", "embed_memory"], required=True
            )
            command.add_argument("--old-version")
            command.add_argument("--new-version")
        if name == "rebuild-model":
            command.add_argument("--model", required=True, help="old embedding model")
            command.add_argument("--key", required=True, help="unique operation key")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
