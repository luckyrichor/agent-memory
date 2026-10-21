"""Materialize the approved current query version for the ordinary evaluation runner."""

import argparse, json
from pathlib import Path
from agent_memory.evals.query_registry import materialize_active_queries

p = argparse.ArgumentParser()
p.add_argument("--registry", type=Path, default=Path("docs/evals/chinese-query-current.json"))
p.add_argument("--output", type=Path, required=True)
a = p.parse_args()
print(json.dumps(materialize_active_queries(a.registry, a.output)))
