"""Reproduce old AND vs corrected OR SQL on identical public raw turns, no LLM."""

import argparse
import json
from pathlib import Path

from sqlalchemy import create_engine, text
from testcontainers.community.postgres import PostgresContainer

from agent_memory.evals.datasets import Conversation, file_hash

p = argparse.ArgumentParser()
p.add_argument("--dataset", type=Path, required=True)
p.add_argument("--output", type=Path, required=True)
a = p.parse_args()
if ".local" not in a.output.resolve().parts:
    p.error("per-query diagnosis stays .local")
conv = Conversation.model_validate_json(a.dataset.read_text())
rows = []
with PostgresContainer("pgvector/pgvector:pg16", driver="psycopg") as pg:
    engine = create_engine(pg.get_connection_url())
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE raw_turns (id text PRIMARY KEY, content text NOT NULL)"))
        conn.execute(
            text("INSERT INTO raw_turns VALUES (:id,:content)"),
            [{"id": d.source_id, "content": d.text} for d in conv.documents],
        )
        for q in conv.questions:
            counts = conn.execute(
                text("""SELECT
                count(*) FILTER (WHERE to_tsvector('simple',content) @@ plainto_tsquery('simple',:q)),
                count(*) FILTER (WHERE to_tsvector('english',content) @@ to_tsquery('english',
                  replace(plainto_tsquery('english',:q)::text,' & ',' | '))) FROM raw_turns"""),
                {"q": q.text},
            ).one()
            rows.append(
                {
                    "question_id": q.question_id,
                    "old_and_matches": counts[0],
                    "new_or_matches": counts[1],
                    "abstention": q.abstention,
                }
            )
    engine.dispose()
summary = {
    "source_sha256": file_hash(a.dataset),
    "source_turns": len(conv.documents),
    "questions": len(rows),
    "old_and_queries_with_matches": sum(r["old_and_matches"] > 0 for r in rows),
    "old_and_queries_without_matches": sum(r["old_and_matches"] == 0 for r in rows),
    "new_or_queries_with_matches": sum(r["new_or_matches"] > 0 for r in rows),
    "scope": "same raw-turn texts, actual disposable PG; diagnostic only, not service import bypass",
    "records": rows,
}
a.output.write_text(json.dumps(summary, indent=2))
print(json.dumps({k: v for k, v in summary.items() if k != "records"}))
