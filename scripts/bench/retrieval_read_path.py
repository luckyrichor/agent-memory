"""Read-path micro-benchmark for the real MemoryRetriever against a throw-away PostgreSQL.

Seeds N active memories by SQL (so seeding 10^4-10^5 rows is fast), then times
``MemoryRetriever.search`` as the RLS-bound application role, one session per query like the API.

The SAME file is run against two source trees for a before/after pair:
    python scripts/bench/retrieval_read_path.py --label before --src /path/to/old/src ...
    python scripts/bench/retrieval_read_path.py --label after  ...
It only uses the public ``MemoryRetriever(PostgresCandidateProvider(session))`` surface, which is
identical in both trees.

Reported per query class: end-to-end latency p50/p95, rows each channel returned, and the body
bytes the database had to ship to Python for the candidate stage (old: every candidate row;
new: only the requested page).  Estimated from string lengths, not from the wire.

Does NOT measure: HTTP, JWT, query-embedding calls, separate load host.  Client and database share
one machine; numbers show relative effect only.  Vectors are random fixtures, not semantics.
"""
import argparse
import asyncio
import json
import os
import platform
import statistics
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "dev"))

TENANT = UUID("88000000-0000-0000-0000-000000000001")
USER = UUID("88000000-0000-0000-0000-000000000002")
VOCAB = ["deploy", "build", "failure", "config", "retry", "timeout", "cache", "index", "query", "session", "token", "worker", "queue", "lease", "schema", "migration", "rollback", "latency", "memory", "tenant", "policy", "review", "alert", "metric", "trace", "service", "database", "vector", "search", "rank", "score", "budget", "context", "window", "summary", "event", "outbox", "job", "status", "error", "handler", "client", "server", "request", "response", "limit", "batch", "stream", "commit"]


def git_commit(tree: Path) -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=tree, check=True,
                              capture_output=True, text=True).stdout.strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, round(q * (len(ordered) - 1))))]


def seed(connection, text, count: int, content_words: int, with_vectors: bool) -> None:
    vocab = "{" + ",".join(VOCAB) + "}"
    connection.execute(text("SELECT setseed(0.42)"))
    connection.execute(text("""
        CREATE TEMP TABLE seed AS
        SELECT g, gen_random_uuid() AS mid, gen_random_uuid() AS vid,
               'topic' || (g % 200) || ' area' || (g % 37) || ' ' || (
                 SELECT string_agg((CAST(:vocab AS text[]))[1 + floor(random() * :n)::int], ' ')
                 FROM generate_series(1, :words) WHERE g > 0) AS body
        FROM generate_series(1, :count) g"""),
        {"vocab": vocab, "n": len(VOCAB), "words": content_words, "count": count})
    connection.execute(text(
        "INSERT INTO memories (tenant_id, memory_id, memory_type, status, scope_kind, workspace_id,"
        " subject_user_id, visibility, owner_user_id, current_version_id, revision, created_at,"
        " updated_at) SELECT :t, mid, 'semantic', 'active', "
        " CASE WHEN g % 2 = 0 THEN 'workspace' ELSE 'tenant' END,"
        " CASE WHEN g % 2 = 0 THEN 'project-a' END, NULL, 'scope', :u, vid, 1,"
        " now() - (g || ' seconds')::interval, now() - (g || ' seconds')::interval FROM seed"),
        {"t": TENANT, "u": USER})
    connection.execute(text(
        "INSERT INTO memory_versions (tenant_id, memory_version_id, memory_id, version_number,"
        " content, structured_content, content_hash, confidence, utility, authority_level,"
        " verification_status, created_at) SELECT :t, vid, mid, 1, body, '{}', md5(body), 0.5, 0.5,"
        " 2, 'unverified', now() FROM seed"), {"t": TENANT})
    if with_vectors:
        connection.execute(text(
            "INSERT INTO memory_embeddings (tenant_id, memory_version_id, model, embedding,"
            " updated_at) SELECT :t, vid, 'bench-fixture',"
            " ('[' || array_to_string(ARRAY(SELECT random() - 0.5 FROM generate_series(1, 1024)),"
            " ',') || ']')::vector, now() FROM seed"), {"t": TENANT})
    connection.execute(text("DROP TABLE seed"))


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True)
    parser.add_argument("--src", type=Path, default=ROOT / "src", help="source tree to benchmark")
    parser.add_argument("--rows", type=int, default=10000)
    parser.add_argument("--content-words", type=int, default=120, help="~6 bytes per word")
    parser.add_argument("--queries", type=int, default=20, help="queries per class")
    parser.add_argument("--with-vectors", action="store_true")
    parser.add_argument("--database-url")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    sys.path.insert(0, str(args.src))

    import random

    import localpg
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine as create_sync
    from sqlalchemy import text
    from sqlalchemy.engine import make_url

    from agent_memory.application.retrieval import MemoryRetriever, RetrievalQuery
    from agent_memory.domain.principal import RequestPrincipal
    from agent_memory.infrastructure.db import (
        create_engine,
        create_session_factory,
        session_for_principal,
    )
    from agent_memory.infrastructure.retrieval import PostgresCandidateProvider

    cluster = None
    if args.database_url is None:
        cluster = localpg.LocalPostgres(username="agent_memory", password="bench-only",
                                        dbname="agent_memory", driver="psycopg")
        cluster.__enter__()
        owner_url = cluster.get_connection_url()
    else:
        owner_url = args.database_url
    try:
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
            vector_version = connection.execute(text(
                "SELECT extversion FROM pg_extension WHERE extname='vector'")).scalar()
            avg_bytes = connection.execute(text(
                "SELECT round(avg(length(content))) FROM memory_versions")).scalar()
        app_url = make_url(owner_url).set(
            drivername="postgresql+psycopg_async", username="bench_app", password="bench-app"
        ).render_as_string(hide_password=False)
        engine = create_engine(app_url)
        sessions = create_session_factory(engine)
        principal = RequestPrincipal(TENANT, USER, frozenset({"developer"}),
                                     frozenset({"memory:read"}), frozenset({"project-a"}))
        rng = random.Random(7)
        qvec = tuple(rng.random() - 0.5 for _ in range(1024))
        classes = {
            # marker words only (topicN or areaM): a small fraction of rows match
            "lexical_narrow": [RetrievalQuery(f"topic{rng.randrange(200)} area{rng.randrange(37)}", limit=20)
                               for _ in range(args.queries)],
            # common vocabulary words: matches (nearly) every row, the 1000-row cap is hit
            "lexical_broad": [RetrievalQuery(" ".join(rng.sample(VOCAB, 3)), limit=20)
                              for _ in range(args.queries)],
            # workspace filter -> structured channel (cap 1000) plus lexical
            "lexical_plus_structured": [RetrievalQuery(f"topic{rng.randrange(200)} area{rng.randrange(37)}",
                                                       workspace_id="project-a", limit=20)
                                        for _ in range(args.queries)],
        }
        if args.with_vectors:
            classes["vector_plus_lexical"] = [
                RetrievalQuery(f"topic{rng.randrange(200)} area{rng.randrange(37)}", vector=qvec,
                               model="bench-fixture", limit=20) for _ in range(args.queries)]

        async def one(query) -> tuple[float, dict[str, int], int]:
            started = asyncio.get_running_loop().time()
            async with session_for_principal(sessions, principal) as session:
                provider = PostgresCandidateProvider(session)
                page = await MemoryRetriever(provider).search(query, principal)
                elapsed = asyncio.get_running_loop().time() - started
                # body bytes shipped by the candidate stage (not timed)
                cands = await provider.candidates(query, principal)
                if cands and hasattr(cands[0], "content"):
                    shipped = sum(len(c.content.encode()) for c in cands)  # old: every row
                else:
                    shipped = sum(len(h.content.encode()) for h in page.items)  # new: page only
            return elapsed, page.channel_counts, shipped

        for query in next(iter(classes.values()))[:3]:  # warm-up, discarded
            await one(query)
        report: dict[str, dict] = {}
        for name, queries in classes.items():
            latencies, shipped, counts = [], [], []
            for query in queries:
                elapsed, channel_counts, size = await one(query)
                latencies.append(elapsed)
                shipped.append(size)
                counts.append(channel_counts)
            report[name] = {
                "n": len(latencies),
                "p50_ms": round(percentile(latencies, 0.5) * 1000, 1),
                "p95_ms": round(percentile(latencies, 0.95) * 1000, 1),
                "mean_ms": round(statistics.fmean(latencies) * 1000, 1),
                "median_channel_rows": {
                    channel: int(statistics.median(c[channel] for c in counts))
                    for channel in ("lexical", "vector", "structured")},
                "median_body_bytes_from_db": int(statistics.median(shipped)),
            }
        await engine.dispose()
        result = {
            "label": args.label, "src_tree": str(args.src), "commit": git_commit(args.src.parent),
            "measured_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
            "environment": {
                "host": platform.node(), "cpus": os.cpu_count(), "python": platform.python_version(),
                "postgres": version, "pgvector": vector_version,
                "client_and_database_same_host": True,
                "vectors": "random fixture (not semantic)" if args.with_vectors else "none"},
            "data": {"rows": args.rows, "avg_content_bytes": int(avg_bytes),
                     "queries_per_class": args.queries},
            "classes": report,
            "note": "body bytes are string-length estimates; old tree ships every candidate "
                    "body, new tree only the requested page",
        }
        out = json.dumps(result, ensure_ascii=False, indent=2)
        print(out)
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(out + "\n")
    finally:
        if cluster is not None:
            cluster.__exit__(None, None, None)


if __name__ == "__main__":
    asyncio.run(main())
