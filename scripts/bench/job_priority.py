"""C4: does priority keep an interactive write out of a bulk backlog? (mixed-load latency)

Runs the real dispatch + extraction worker processes against a throw-away PostgreSQL, pushes a
bulk backlog of events that will take a while to drain, then submits a few "interactive" events
while that backlog is still being worked on, and reports ingest -> retrievable latency per class.

``--priority off`` never touches the priority column, so the same script runs unchanged against the
pre-C4 commit (everything is first-in-first-out there). ``--priority on`` marks the bulk events
``bulk`` and the late arrivals ``interactive``.

What this does NOT measure: real model latency (rule extractor), the outbox hop (dispatch stays
first-in-first-out on purpose), or a load generator on a separate host.
"""
import argparse
import asyncio
import json
import os
import platform
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "dev"))
sys.path.insert(0, str(ROOT / "src"))

TENANT = UUID("79000000-0000-0000-0000-000000000001")
USER = UUID("79000000-0000-0000-0000-000000000002")


def percentile(values: list[float], q: float) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(q * (len(ordered) - 1))))
    return ordered[index]


def summary(values: list[float]) -> dict[str, float | int]:
    return {
        "n": len(values),
        "p50_s": round(percentile(values, 0.5), 3),
        "p95_s": round(percentile(values, 0.95), 3),
        "max_s": round(max(values), 3) if values else float("nan"),
        "mean_s": round(statistics.fmean(values), 3) if values else float("nan"),
    }


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True)
    parser.add_argument("--bulk", type=int, default=1500)
    parser.add_argument("--interactive", type=int, default=5)
    parser.add_argument("--priority", choices=["on", "off"], default="on")
    parser.add_argument("--settle", type=float, default=1.0,
                        help="seconds to let the backlog build before the interactive events")
    parser.add_argument("--timeout", type=float, default=600)
    parser.add_argument("--database-url", help="existing superuser URL; otherwise a local cluster")
    parser.add_argument("--reset", action="store_true",
                        help="with --database-url: drop and recreate the public schema first")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url

    cluster = None
    if args.database_url is None:
        import localpg

        cluster = localpg.LocalPostgres(username="agent_memory", password="bench-only",
                                        dbname="agent_memory", driver="psycopg")
        cluster.__enter__()
        owner_url = cluster.get_connection_url()
    else:
        owner_url = args.database_url

    procs: list[subprocess.Popen[bytes]] = []
    try:
        owner = create_engine(owner_url)
        if args.database_url is not None and args.reset:
            with owner.begin() as connection:
                connection.execute(text("DROP SCHEMA public CASCADE"))
                connection.execute(text("CREATE SCHEMA public"))
        owner.dispose()
        config = Config(str(ROOT / "alembic.ini"))
        config.set_main_option("script_location", str(ROOT / "migrations"))
        config.set_main_option("sqlalchemy.url", owner_url)
        command.upgrade(config, "head")
        owner = create_engine(owner_url)
        with owner.begin() as connection:
            connection.execute(text(
                "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='bench_app') "
                "THEN CREATE ROLE bench_app LOGIN PASSWORD 'bench-app' NOSUPERUSER NOBYPASSRLS; "
                "END IF; END $$"))
            connection.execute(text("GRANT agent_memory_app TO bench_app"))
            version = connection.execute(text("SHOW server_version")).scalar()
        app_url = make_url(owner_url).set(
            drivername="postgresql+psycopg_async", username="bench_app", password="bench-app"
        ).render_as_string(hide_password=False)

        health = tempfile.mkdtemp(prefix="bench-health-")
        env = dict(os.environ, MEMORY_DATABASE_URL=app_url, MEMORY_WORKER_HEALTH_DIR=health,
                   MEMORY_LOG_LEVEL="WARNING", PYTHONPATH=str(ROOT / "src"))
        for spec in (
            [sys.executable, "-m", "agent_memory.workers.extraction", "dispatch",
             "--tenant-id", str(TENANT)],
            [sys.executable, "-m", "agent_memory.workers.extraction", "work",
             "--tenant-id", str(TENANT), "--worker-id", "bench-extract"],
        ):
            procs.append(subprocess.Popen(spec, env=env, stdout=subprocess.DEVNULL,
                                          stderr=subprocess.DEVNULL))
        await asyncio.sleep(3)

        from agent_memory.domain.enums import ScopeKind
        from agent_memory.domain.events import EventDraft, EventType
        from agent_memory.domain.models import MemoryScope
        from agent_memory.domain.principal import RequestPrincipal
        from agent_memory.domain.jobs import JobPriority
        from agent_memory.infrastructure.db import (
            create_engine as create_async,
            create_session_factory,
            session_for_principal,
        )
        from agent_memory.infrastructure.event_repositories import PostgresEventIngestionRepository

        engine = create_async(app_url)
        sessions = create_session_factory(engine)
        principal = RequestPrincipal(TENANT, USER, frozenset({"developer"}),
                                     frozenset({"memory:write"}), frozenset({"project-a"}))
        run_id = uuid4().hex[:8]
        sent: dict[str, float] = {}
        active_at: dict[str, float] = {}
        stop = asyncio.Event()

        def draft(key: str, sequence: int) -> EventDraft:
            return EventDraft(
                idempotency_key=key, session_id=f"s-{run_id}", sequence_number=sequence,
                event_type=EventType.TOOL_RESULT, agent_id="bench",
                occurred_at=datetime.now(UTC),
                scope=MemoryScope(ScopeKind.WORKSPACE, "project-a", None),
                payload={"tool_name": "build", "exit_code": 1, "summary": key},
            )

        async def ingest(keys: list[str], start_sequence: int, priority: int | None) -> None:
            for offset, key in enumerate(keys):
                async with session_for_principal(sessions, principal) as session:
                    repository = PostgresEventIngestionRepository(
                        session, new_id=uuid4, now=lambda: datetime.now(UTC)
                    )
                    if priority is None:
                        await repository.ingest_batch(TENANT, USER, (draft(key, start_sequence + offset),))
                    else:
                        await repository.ingest_batch(
                            TENANT, USER, (draft(key, start_sequence + offset),), priority=priority
                        )
                sent[key] = time.monotonic()

        async def poll() -> None:
            query = text(
                "SELECT v.content FROM memories m JOIN memory_versions v "
                "  ON v.tenant_id=m.tenant_id AND v.memory_version_id=m.current_version_id "
                "WHERE m.status='active' AND v.content LIKE :pattern")
            with owner.connect() as connection:
                while not stop.is_set():
                    now = time.monotonic()
                    for (content,) in connection.execute(
                            query, {"pattern": f"bench-{run_id}-%"}):
                        active_at.setdefault(content, now)
                    connection.rollback()
                    await asyncio.sleep(0.02)

        poller = asyncio.create_task(poll())
        interactive_keys = [f"bench-{run_id}-live-{index:02d}"
                            for index in range(args.interactive)]
        bulk_keys = [f"bench-{run_id}-bulk-{index:05d}" for index in range(args.bulk)]
        started = time.monotonic()
        await ingest(
            bulk_keys,
            1,
            None if args.priority == "off" else int(JobPriority.BULK),
        )
        await asyncio.sleep(args.settle)
        await ingest(
            interactive_keys,
            len(bulk_keys) + 1,
            None if args.priority == "off" else int(JobPriority.INTERACTIVE),
        )
        deadline = time.monotonic() + args.timeout
        while time.monotonic() < deadline and len(active_at) < len(bulk_keys) + len(interactive_keys):
            await asyncio.sleep(0.05)
        total = time.monotonic() - started
        stop.set()
        await poller
        await engine.dispose()

        live = [active_at[k] - sent[k] for k in interactive_keys if k in active_at]
        bulk = [active_at[k] - sent[k] for k in bulk_keys if k in active_at]
        result = {
            "label": args.label,
            "commit": subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                                     capture_output=True, text=True).stdout.strip(),
            "dirty_tree": bool(subprocess.run(["git", "status", "--porcelain", "--untracked=no"],
                                              cwd=ROOT, capture_output=True, text=True).stdout),
            "measured_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
            "environment": {
                "host": platform.node(), "cpus": os.cpu_count(),
                "python": platform.python_version(), "postgres": version,
                "extractor": "rule (CodingFailureRuleExtractor)",
                "workers": 1, "clients_workers_database_same_host": True,
            },
            "workload": {"bulk_events": args.bulk, "interactive_events": args.interactive,
                         "priority": args.priority, "settle_s": args.settle},
            "interactive_latency": summary(live),
            "bulk_latency": summary(bulk),
            "completed": len(active_at),
            "total_wall_s": round(total, 2),
            "interactive_finished": len(live),
        }
        text_out = json.dumps(result, ensure_ascii=False, indent=2)
        print(text_out)
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(text_out + "\n")
    finally:
        for proc in procs:
            proc.terminate()
        for proc in procs:
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
        if cluster is not None:
            cluster.__exit__(None, None, None)


if __name__ == "__main__":
    asyncio.run(main())
