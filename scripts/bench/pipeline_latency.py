"""Write-to-searchable latency of the REAL worker processes (O5 measurement).

Starts a throw-away PostgreSQL (or uses --database-url), runs the three real worker CLIs
(outbox dispatch, extraction, embedding with the deterministic fixture provider) as
subprocesses, submits build-failure events, and records when each event's memory becomes
(a) active/retrievable by the lexical channel and (b) vector-ready (embedding row exists).

What this does NOT measure: model latency (rule extractor + fixture embedding take ~0 ms),
semantic quality, or a separate load host. The numbers show queueing/polling overhead of the
pipeline itself; client, workers and database share one machine.

Examples
  steady (one event every 1.5 s, shows per-event wake-up delay):
    python scripts/bench/pipeline_latency.py --label before --events 20 --interval 1.5
  burst (all at once, shows how fast a backlog drains):
    python scripts/bench/pipeline_latency.py --label before-burst --events 60 --interval 0
  Extra worker flags (new code): --dispatch-args "--poll-seconds 30" --embed-args "..."
"""
import argparse
import asyncio
import json
import os
import platform
import shlex
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

TENANT = UUID("77000000-0000-0000-0000-000000000001")
USER = UUID("77000000-0000-0000-0000-000000000002")


def git_commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, check=True,
                              capture_output=True, text=True).stdout.strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def percentile(values: list[float], q: float) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(q * (len(ordered) - 1))))
    return ordered[index]


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True)
    parser.add_argument("--events", type=int, default=20)
    parser.add_argument("--interval", type=float, default=1.5, help="seconds between events; 0 = burst")
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--database-url", help="owner/superuser SQLAlchemy URL (psycopg driver)")
    parser.add_argument("--dispatch-args", default="")
    parser.add_argument("--work-args", default="")
    parser.add_argument("--embed-args", default="")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url

    cluster = None
    if args.database_url is None:
        import localpg  # scripts/dev: Docker-free throw-away PostgreSQL

        cluster = localpg.LocalPostgres(username="agent_memory", password="bench-only",
                                        dbname="agent_memory", driver="psycopg")
        cluster.__enter__()
        owner_url = cluster.get_connection_url()
    else:
        owner_url = args.database_url
    procs: list[subprocess.Popen[bytes]] = []
    try:
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
            vector_version = connection.execute(text(
                "SELECT extversion FROM pg_extension WHERE extname='vector'")).scalar()
        app_url = make_url(owner_url).set(
            drivername="postgresql+psycopg_async", username="bench_app", password="bench-app"
        ).render_as_string(hide_password=False)

        health = tempfile.mkdtemp(prefix="bench-health-")
        env = dict(os.environ, MEMORY_DATABASE_URL=app_url, MEMORY_WORKER_HEALTH_DIR=health,
                   MEMORY_LOG_LEVEL="WARNING", PYTHONPATH=str(ROOT / "src"))
        py = sys.executable
        tenant = str(TENANT)
        specs = [
            [py, "-m", "agent_memory.workers.extraction", "dispatch", "--tenant-id", tenant,
             *shlex.split(args.dispatch_args)],
            [py, "-m", "agent_memory.workers.extraction", "work", "--tenant-id", tenant,
             "--worker-id", "bench-extract", *shlex.split(args.work_args)],
            [py, "-m", "agent_memory.workers.embedding", "work", "--tenant-id", tenant,
             "--worker-id", "bench-embed", "--fixture", *shlex.split(args.embed_args)],
        ]
        for spec in specs:
            procs.append(subprocess.Popen(spec, env=env, stdout=subprocess.DEVNULL,
                                          stderr=subprocess.DEVNULL))
        await asyncio.sleep(3)  # let workers start and run their first (empty) iteration

        from agent_memory.domain.enums import ScopeKind
        from agent_memory.domain.events import EventDraft, EventType
        from agent_memory.domain.models import MemoryScope
        from agent_memory.domain.principal import RequestPrincipal
        from agent_memory.infrastructure.db import (
            create_engine as create_async,
        )
        from agent_memory.infrastructure.db import (
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
        vector_at: dict[str, float] = {}
        start = time.monotonic()
        stop = asyncio.Event()

        async def poll() -> None:
            query = text(
                "SELECT v.content, m.status, e.memory_version_id IS NOT NULL AS has_vec "
                "FROM memories m JOIN memory_versions v "
                "  ON v.tenant_id=m.tenant_id AND v.memory_version_id=m.current_version_id "
                "LEFT JOIN memory_embeddings e "
                "  ON e.tenant_id=v.tenant_id AND e.memory_version_id=v.memory_version_id "
                "WHERE v.content LIKE :pattern")
            with owner.connect() as connection:
                while not stop.is_set():
                    now = time.monotonic()
                    for content, status, has_vec in connection.execute(
                            query, {"pattern": f"bench-{run_id}-%"}):
                        if status == "active" and content not in active_at:
                            active_at[content] = now
                        if has_vec and content not in vector_at:
                            vector_at[content] = now
                    connection.rollback()
                    await asyncio.sleep(0.02)

        poller = asyncio.create_task(poll())
        for index in range(args.events):
            key = f"bench-{run_id}-{index:04d}"
            draft = EventDraft(
                idempotency_key=key, session_id=f"s-{run_id}", sequence_number=index + 1,
                event_type=EventType.TOOL_RESULT, agent_id="bench",
                occurred_at=datetime.now(UTC),
                scope=MemoryScope(ScopeKind.WORKSPACE, "project-a", None),
                payload={"tool_name": "build", "exit_code": 1, "summary": key})
            async with session_for_principal(sessions, principal) as session:
                await PostgresEventIngestionRepository(
                    session, new_id=uuid4, now=lambda: datetime.now(UTC)
                ).ingest_batch(TENANT, USER, (draft,))
            sent[key] = time.monotonic()
            if args.interval:
                await asyncio.sleep(args.interval)
        deadline = time.monotonic() + args.timeout
        while time.monotonic() < deadline and len(vector_at) < args.events:
            await asyncio.sleep(0.1)
        total = time.monotonic() - start
        stop.set()
        await poller
        await engine.dispose()

        lat_active = [active_at[k] - sent[k] for k in sent if k in active_at]
        lat_vector = [vector_at[k] - sent[k] for k in sent if k in vector_at]

        def summary(values: list[float]) -> dict[str, float | int]:
            return {
                "n": len(values),
                "p50_s": round(percentile(values, 0.5), 3),
                "p95_s": round(percentile(values, 0.95), 3),
                "max_s": round(max(values), 3) if values else float("nan"),
                "mean_s": round(statistics.fmean(values), 3) if values else float("nan"),
            }

        last_vec = max(vector_at.values()) if vector_at else None
        first_send = min(sent.values())
        result = {
            "label": args.label,
            "commit": git_commit(),
            "measured_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
            "environment": {
                "host": platform.node(), "cpus": os.cpu_count(), "python": platform.python_version(),
                "postgres": version, "pgvector": vector_version,
                "client_workers_database_same_host": True,
                "extractor": "rule (CodingFailureRuleExtractor)",
                "embedding": "fixture-sha256-1024-v1 (NOT a semantic model, ~0 ms)",
            },
            "workload": {"events": args.events, "interval_s": args.interval,
                         "dispatch_args": args.dispatch_args, "work_args": args.work_args,
                         "embed_args": args.embed_args},
            "extraction_visible": summary(lat_active),
            "vector_ready": summary(lat_vector),
            "completed": len(vector_at), "total_wall_s": round(total, 2),
            "drain_s_first_send_to_last_vector": (
                round(last_vec - first_send, 2) if last_vec else None),
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
