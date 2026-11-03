"""B3: does an approximate vector index (HNSW) help, and what does it break? (O2)

Runs the REAL ``PostgresCandidateProvider`` vector channel as the RLS-bound application role
against clustered synthetic 1024-d vectors in one big tenant and several small tenants, with and
without a global HNSW index, and reports per tenant class:
  * candidates returned (the "filter after approximate search leaves too few rows" problem),
  * recall@K against the exact (no-index) result of the same query,
  * latency p50/p95,
  * whether the planner used the HNSW index at all (EXPLAIN of the SQL the provider sent).

The "too few rows" problem is what ``hnsw.iterative_scan`` (pgvector >= 0.8) fixes: without it a
filtered approximate scan stops after roughly ``ef_search`` rows. Both variants are measured, so
the version requirement is visible in the numbers instead of being asserted.

Limits: random clustered vectors are not a semantic embedding; client and database share one
machine. Numbers show index behaviour, not retrieval quality on real data.
"""
import argparse
import asyncio
import json
import os
import platform
import random
import statistics
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "dev"))
sys.path.insert(0, str(ROOT / "src"))

USER = UUID("78000000-0000-0000-0000-000000000002")
MODEL = "bench-fixture"


def pct(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(q * (len(ordered) - 1)))]


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True)
    parser.add_argument("--big", type=int, default=16000)
    parser.add_argument("--small-tenants", type=int, default=8)
    parser.add_argument("--small-size", type=int, default=500)
    parser.add_argument("--queries", type=int, default=30)
    parser.add_argument("--ef-search", default="40,200,1000")
    parser.add_argument("--k", type=int, default=20, help="recall@k")
    parser.add_argument("--database-url", help="existing superuser URL; otherwise a local cluster")
    parser.add_argument("--reset", action="store_true",
                        help="with --database-url: drop and recreate the public schema first")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    import psycopg
    from alembic import command
    from alembic.config import Config
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

    cluster = None
    if args.database_url is None:
        import localpg

        cluster = localpg.LocalPostgres(username="agent_memory", password="bench-only",
                                        dbname="agent_memory", driver="psycopg")
        cluster.__enter__()
        owner_url = cluster.get_connection_url()
    else:
        owner_url = args.database_url
    try:
        owner = create_sync(owner_url)
        if args.database_url is not None and args.reset:
            with owner.begin() as connection:
                connection.execute(text("DROP SCHEMA public CASCADE"))
                connection.execute(text("CREATE SCHEMA public"))
        owner.dispose()
        config = Config(str(ROOT / "alembic.ini"))
        config.set_main_option("script_location", str(ROOT / "migrations"))
        config.set_main_option("sqlalchemy.url", owner_url)
        command.upgrade(config, "head")
        owner = create_sync(owner_url)
        # Migration 0014 ships the index; the baselines below need it gone, and the index runs
        # re-create it with the same name so the numbers describe the deployed object.
        with owner.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            connection.execute(text("DROP INDEX IF EXISTS ix_memory_embeddings_hnsw"))
        big = uuid4()
        smalls = [uuid4() for _ in range(args.small_tenants)]
        sizes = {big: args.big, **{t: args.small_size for t in smalls}}
        t0 = time.monotonic()
        with owner.begin() as connection:
            connection.execute(text(
                "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='bench_app') "
                "THEN CREATE ROLE bench_app LOGIN PASSWORD 'bench-app' NOSUPERUSER NOBYPASSRLS; "
                "END IF; END $$"))
            connection.execute(text("GRANT agent_memory_app TO bench_app"))
            connection.execute(text("SELECT setseed(0.42)"))
            connection.execute(text(
                "CREATE TEMP TABLE centers AS SELECT k, ARRAY(SELECT random() - 0.5 "
                "FROM generate_series(1, 1024)) AS c FROM generate_series(1, 50) k"))
            for tenant, count in sizes.items():
                connection.execute(text(
                    "CREATE TEMP TABLE seed AS SELECT g, gen_random_uuid() AS mid, "
                    "gen_random_uuid() AS vid, 1 + (g % 50) AS k FROM generate_series(1, :n) g"),
                    {"n": count})
                connection.execute(text(
                    "INSERT INTO memories (tenant_id, memory_id, memory_type, status, scope_kind,"
                    " workspace_id, subject_user_id, visibility, owner_user_id, current_version_id,"
                    " revision, created_at, updated_at) SELECT :t, mid, 'semantic', 'active',"
                    " 'tenant', NULL, NULL, 'scope', :u, vid, 1, now(), now() FROM seed"),
                    {"t": tenant, "u": USER})
                connection.execute(text(
                    "INSERT INTO memory_versions (tenant_id, memory_version_id, memory_id,"
                    " version_number, content, structured_content, content_hash, confidence,"
                    " utility, authority_level, verification_status, created_at)"
                    " SELECT :t, vid, mid, 1, 'v' || g, '{}', md5('v' || g), 0.5, 0.5, 2,"
                    " 'unverified', now() FROM seed"), {"t": tenant})
                connection.execute(text(
                    "INSERT INTO memory_embeddings (tenant_id, memory_version_id, model, embedding,"
                    " updated_at) SELECT :t, s.vid, :m, ('[' || array_to_string(ARRAY("
                    "SELECT c.c[i] + (random() - 0.5) * 0.3 FROM generate_series(1, 1024) i),"
                    " ',') || ']')::vector, now() FROM seed s JOIN centers c ON c.k = s.k"),
                    {"t": tenant, "m": MODEL})
                connection.execute(text("DROP TABLE seed"))
            connection.execute(text("ANALYZE"))
            version = connection.execute(text("SHOW server_version")).scalar()
            vector_version = connection.execute(text(
                "SELECT extversion FROM pg_extension WHERE extname='vector'")).scalar()
        seed_s = round(time.monotonic() - t0, 1)

        # Query vectors: noisy copies of stored vectors of the same tenant.
        rng = random.Random(11)
        queries: dict[str, list[tuple[float, ...]]] = {}
        with owner.connect() as connection:
            for name, tenant in (("big", big), ("small", smalls[0])):
                rows = connection.execute(text(
                    "SELECT embedding::text FROM memory_embeddings WHERE tenant_id=:t "
                    "ORDER BY random() LIMIT :n"), {"t": tenant, "n": args.queries}).all()
                queries[name] = [
                    tuple(float(x) + rng.gauss(0, 0.05) for x in row[0].strip("[]").split(","))
                    for row in rows
                ]
        tenants = {"big": big, "small": smalls[0]}

        app_url = make_url(owner_url).set(
            drivername="postgresql+psycopg_async", username="bench_app", password="bench-app"
        ).render_as_string(hide_password=False)
        sync_app_url = make_url(owner_url).set(
            drivername="postgresql", username="bench_app", password="bench-app"
        ).render_as_string(hide_password=False)

        async def run_config(label: str, truth: dict | None) -> tuple[dict, dict]:
            engine = create_engine(app_url)
            sessions = create_session_factory(engine)
            captured: list[tuple[str, object]] = []

            @event.listens_for(engine.sync_engine, "before_cursor_execute")
            def capture(conn, cursor, statement, parameters, context, executemany):
                captured.append((statement, parameters))

            result: dict[str, dict] = {}
            ranked: dict[str, list[list[UUID]]] = {}
            for name, vectors in queries.items():
                principal = RequestPrincipal(tenants[name], USER, frozenset({"developer"}),
                                             frozenset({"memory:read"}), frozenset())
                latencies: list[float] = []
                counts: list[int] = []
                recalls: list[float] = []
                ranked[name] = []
                for index, vector in enumerate(vectors):
                    captured.clear()
                    started = time.perf_counter()
                    async with session_for_principal(sessions, principal) as session:
                        candidates = await PostgresCandidateProvider(session).candidates(
                            RetrievalQuery("", vector=vector, model=MODEL, limit=args.k), principal)
                    latencies.append((time.perf_counter() - started) * 1000)
                    ids = [c.memory_id for c in candidates]
                    counts.append(len(ids))
                    ranked[name].append(ids)
                    if truth is not None:
                        want = set(truth[name][index][: args.k])
                        recalls.append(len(want & set(ids[: args.k])) / max(1, len(want)))
                selects = [(s, p) for s, p in captured
                           if s.lstrip().upper().startswith("SELECT") and "FROM memories" in s]
                with psycopg.connect(sync_app_url) as plain:
                    plain.execute("SELECT set_config('app.current_tenant_id', %s, false)",
                                  (str(tenants[name]),))
                    plan = plain.execute("EXPLAIN (FORMAT JSON) " + selects[-1][0],
                                         selects[-1][1]).fetchone()[0][0]["Plan"]
                nodes: list[str] = []

                def walk(node: dict) -> None:
                    nodes.append(node["Node Type"] + (
                        f"[{node['Index Name']}]" if "Index Name" in node else ""))
                    for child in node.get("Plans", []):
                        walk(child)

                walk(plan)
                result[name] = {
                    "p50_ms": round(statistics.median(latencies), 1),
                    "p95_ms": round(pct(latencies, 0.95), 1),
                    "candidates_min": min(counts), "candidates_median": statistics.median(counts),
                    "recall_at_k_mean": round(statistics.fmean(recalls), 4) if recalls else 1.0,
                    "recall_at_k_min": round(min(recalls), 4) if recalls else 1.0,
                    "uses_hnsw_index": any("hnsw" in n.lower() for n in nodes),
                    "plan_nodes": nodes,
                }
            await engine.dispose()
            return result, ranked

        report: dict[str, dict] = {}
        exact, truth = await run_config("exact", None)
        report["exact_no_index"] = exact

        # Variant 2: index-friendly SQL shape (nearest-first on the embeddings table, then join),
        # which is the only shape in which the planner can use the HNSW index at all.
        two_step_sql = (
            "WITH nearest AS MATERIALIZED ("
            " SELECT e.memory_version_id, e.embedding <=> %(q)s::vector AS distance"
            " FROM memory_embeddings e WHERE e.model = %(model)s"
            "  AND e.tenant_id = nullif(current_setting('app.current_tenant_id', true), '')::uuid"
            " ORDER BY e.embedding <=> %(q)s::vector LIMIT %(lim)s)"
            " SELECT m.memory_id FROM nearest n JOIN memories m"
            "  ON m.tenant_id = nullif(current_setting('app.current_tenant_id', true), '')::uuid"
            "  AND m.current_version_id = n.memory_version_id AND m.status = 'active'"
            " ORDER BY n.distance LIMIT 1000")
        def run_two_step(ef: int | None, iterative: bool = False) -> dict[str, dict]:
            per_class: dict[str, dict] = {}
            for name, vectors in queries.items():
                latencies, counts, recalls = [], [], []
                with psycopg.connect(sync_app_url, autocommit=False) as plain:
                    plain.execute("SELECT set_config('app.current_tenant_id', %s, false)",
                                  (str(tenants[name]),))
                    if ef is not None:
                        plain.execute(f"SET hnsw.ef_search = {ef}")
                    if iterative:
                        plain.execute("SET hnsw.iterative_scan = relaxed_order")
                    for index, vector in enumerate(vectors):
                        literal = "[" + ",".join(f"{x:.6f}" for x in vector) + "]"
                        params = {"q": literal, "model": MODEL, "lim": 1000}
                        started = time.perf_counter()
                        ids = [r[0] for r in plain.execute(two_step_sql, params).fetchall()]
                        latencies.append((time.perf_counter() - started) * 1000)
                        counts.append(len(ids))
                        want = set(truth[name][index][: args.k])
                        recalls.append(len(want & set(ids[: args.k])) / max(1, len(want)))
                    plan = plain.execute("EXPLAIN (FORMAT TEXT) " + two_step_sql,
                                         params).fetchall()
                per_class[name] = {
                    "p50_ms": round(statistics.median(latencies), 1),
                    "p95_ms": round(pct(latencies, 0.95), 1),
                    "candidates_min": min(counts), "candidates_median": statistics.median(counts),
                    "recall_at_k_mean": round(statistics.fmean(recalls), 4),
                    "recall_at_k_min": round(min(recalls), 4),
                    "uses_hnsw_index": any("hnsw" in row[0].lower() for row in plan),
                }
            return per_class

        report["two_step_shape_no_index"] = run_two_step(None)

        with owner.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            build_started = time.monotonic()
            connection.execute(text(
                "CREATE INDEX ix_memory_embeddings_hnsw ON memory_embeddings "
                "USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)"))
            build_s = round(time.monotonic() - build_started, 1)
            size = connection.execute(text(
                "SELECT pg_size_pretty(pg_relation_size('ix_memory_embeddings_hnsw'))")).scalar()
            table = connection.execute(text(
                "SELECT pg_size_pretty(pg_relation_size('memory_embeddings'))")).scalar()
            for ef in [int(x) for x in args.ef_search.split(",")]:
                connection.execute(text(
                    f'ALTER DATABASE "{make_url(owner_url).database}"'
                    f" SET hnsw.ef_search = {ef}"))
                result, _ = await run_config(f"hnsw_ef{ef}", truth)
                report[f"hnsw_global_ef_search_{ef}"] = result

        iterative_supported = False
        with owner.connect() as connection:
            iterative_supported = connection.execute(text(
                "SELECT current_setting('hnsw.iterative_scan', true)")).scalar() is not None
        for ef in [int(x) for x in args.ef_search.split(",")]:
            report[f"hnsw_two_step_ef_search_{ef}"] = run_two_step(ef)
            if iterative_supported:
                report[f"hnsw_two_step_iterative_ef_search_{ef}"] = run_two_step(
                    ef, iterative=True)
        out = {
            "label": args.label,
            "commit": subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                                     capture_output=True, text=True).stdout.strip(),
            "dirty_tree": bool(subprocess.run(["git", "status", "--porcelain", "--untracked=no"],
                                              cwd=ROOT, capture_output=True, text=True).stdout),
            "measured_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
            "environment": {"host": platform.node(), "cpus": os.cpu_count(),
                            "postgres": version, "pgvector": vector_version,
                            "client_and_database_same_host": True,
                            "vectors": "clustered synthetic (50 centers, noise 0.3), NOT semantic"},
            "data": {"big_tenant_rows": args.big, "small_tenants": args.small_tenants,
                     "small_tenant_rows": args.small_size, "dims": 1024, "seed_seconds": seed_s,
                     "queries_per_class": args.queries, "recall_k": args.k,
                     "candidate_limit": 1000},
            "hnsw": {"m": 16, "ef_construction": 64, "build_seconds": build_s,
                     "index_size": size, "embedding_table_size": table,
                     "iterative_scan_supported": iterative_supported},
            "results": report,
        }
        text_out = json.dumps(out, ensure_ascii=False, indent=2, default=str)
        print(text_out)
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(text_out + "\n")
    finally:
        if cluster is not None:
            cluster.__exit__(None, None, None)


if __name__ == "__main__":
    asyncio.run(main())
