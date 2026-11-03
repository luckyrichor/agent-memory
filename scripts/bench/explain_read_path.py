"""EXPLAIN ANALYZE of the SQL the real PostgresCandidateProvider emits for each channel.

Why not hand-written SQL: whether an expression index is used depends on how the query is
*compiled* (for instance a text-search configuration sent as a bound parameter cannot match an
index on ``to_tsvector('english', ...)``).  So this captures the statements and parameters the
provider actually sends and replays them under EXPLAIN as the RLS-bound application role.

Output per channel: plan node types, whether any index/bitmap scan appears, execution time,
shared buffers hit/read.  Same seeding as retrieval_read_path.py (shared via import).
"""
import argparse
import asyncio
import json
import os
import platform
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "dev"))
sys.path.insert(0, str(ROOT / "scripts" / "bench"))
sys.path.insert(0, str(ROOT / "src"))


def walk(plan: dict, nodes: list[str]) -> None:
    label = plan["Node Type"]
    if "Index Name" in plan:
        label += f"[{plan['Index Name']}]"
    nodes.append(label)
    for child in plan.get("Plans", []):
        walk(child, nodes)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True)
    parser.add_argument("--rows", type=int, default=10000)
    parser.add_argument("--content-words", type=int, default=120)
    parser.add_argument("--with-vectors", action="store_true")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    import random

    import localpg
    import psycopg
    from alembic import command
    from alembic.config import Config
    from retrieval_read_path import TENANT, USER, VOCAB, seed
    from sqlalchemy import create_engine as create_sync
    from sqlalchemy import event, text
    from sqlalchemy.engine import make_url

    from agent_memory.application.retrieval import RetrievalQuery
    from agent_memory.domain.principal import RequestPrincipal
    from agent_memory.infrastructure.db import (
        create_engine,
        create_session_factory,
        session_for_principal,
    )
    from agent_memory.infrastructure.retrieval import PostgresCandidateProvider

    cluster = localpg.LocalPostgres(username="agent_memory", password="bench-only",
                                    dbname="agent_memory", driver="psycopg")
    cluster.__enter__()
    try:
        owner_url = cluster.get_connection_url()
        config = Config(str(ROOT / "alembic.ini"))
        config.set_main_option("script_location", str(ROOT / "migrations"))
        config.set_main_option("sqlalchemy.url", owner_url)
        command.upgrade(config, "head")
        owner = create_sync(owner_url)
        with owner.begin() as connection:
            connection.execute(text(
                "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='bench_app') "
                "THEN CREATE ROLE bench_app LOGIN PASSWORD 'bench-app' NOSUPERUSER NOBYPASSRLS; "
                "END IF; END $$"))
            connection.execute(text("GRANT agent_memory_app TO bench_app"))
            connection.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"),
                               {"t": str(TENANT)})
            seed(connection, text, args.rows, args.content_words, args.with_vectors)
            connection.execute(text("ANALYZE"))
            version = connection.execute(text("SHOW server_version")).scalar()
            indexes = [r[0] for r in connection.execute(text(
                "SELECT indexname FROM pg_indexes WHERE tablename='memory_versions' "
                "ORDER BY 1"))]
        app_url = make_url(owner_url).set(
            drivername="postgresql+psycopg_async", username="bench_app", password="bench-app"
        ).render_as_string(hide_password=False)
        sync_app_url = make_url(owner_url).set(
            drivername="postgresql", username="bench_app", password="bench-app"
        ).render_as_string(hide_password=False)
        engine = create_engine(app_url)
        sessions = create_session_factory(engine)
        principal = RequestPrincipal(TENANT, USER, frozenset({"developer"}),
                                     frozenset({"memory:read"}), frozenset({"project-a"}))
        rng = random.Random(7)
        qvec = tuple(rng.random() - 0.5 for _ in range(1024))
        cases = {
            "english_lexical_narrow": RetrievalQuery("topic17 area5", limit=20),
            "english_lexical_broad": RetrievalQuery("deploy failure cache", limit=20),
            "structured_workspace": RetrievalQuery("", workspace_id="project-a", limit=20),
        }
        if args.with_vectors:
            cases["vector"] = RetrievalQuery("", vector=qvec, model="bench-fixture", limit=20)

        captured: list[tuple[str, object]] = []
        sync_engine = engine.sync_engine

        @event.listens_for(sync_engine, "before_cursor_execute")
        def capture(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
            captured.append((statement, parameters))

        report: dict[str, dict] = {}
        for name, query in cases.items():
            captured.clear()
            async with session_for_principal(sessions, principal) as session:
                await PostgresCandidateProvider(session).candidates(query, principal)
            selects = [(s, p) for s, p in captured if s.lstrip().upper().startswith("SELECT")
                       and "FROM memories" in s]
            statement, parameters = selects[-1]
            with psycopg.connect(sync_app_url) as plain:
                plain.execute("SELECT set_config('app.current_tenant_id', %s, false)",
                              (str(TENANT),))
                # statement uses pyformat/%(name)s placeholders as rendered for psycopg
                rows = plain.execute("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + statement,
                                     parameters).fetchone()[0]
            top = rows[0]
            nodes: list[str] = []
            walk(top["Plan"], nodes)
            report[name] = {
                "execution_ms": round(top["Execution Time"], 1),
                "planning_ms": round(top["Planning Time"], 1),
                "nodes": nodes,
                "uses_index_scan": any("Index" in n or "Bitmap" in n for n in nodes),
                "shared_hit_blocks": top["Plan"].get("Shared Hit Blocks"),
                "shared_read_blocks": top["Plan"].get("Shared Read Blocks"),
                "config_is_bound_parameter": "to_tsvector(%(" in statement,
            }
        await engine.dispose()
        result = {
            "label": args.label,
            "commit": subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                                     capture_output=True, text=True).stdout.strip(),
            "dirty_tree": bool(subprocess.run(["git", "status", "--porcelain", "--untracked=no"],
                                              cwd=ROOT, capture_output=True, text=True).stdout),
            "measured_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
            "environment": {"host": platform.node(), "cpus": os.cpu_count(),
                            "postgres": version, "client_and_database_same_host": True,
                            "vectors": "random fixture" if args.with_vectors else "none"},
            "data": {"rows": args.rows}, "memory_versions_indexes": indexes,
            "channels": report,
        }
        out = json.dumps(result, ensure_ascii=False, indent=2)
        print(out)
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(out + "\n")
    finally:
        cluster.__exit__(None, None, None)


if __name__ == "__main__":
    asyncio.run(main())
