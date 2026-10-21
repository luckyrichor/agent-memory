"""Build private source-grounded queries, preserving existing splits."""
import argparse
import json
from pathlib import Path
from agent_memory.evals.chinese_queries import build_queries
p = argparse.ArgumentParser()
p.add_argument('--normalized', type=Path, required=True)
p.add_argument('--timeline', type=Path, required=True)
p.add_argument('--output', type=Path, required=True)
a = p.parse_args()
print(json.dumps(build_queries(a.normalized, a.timeline, a.output), ensure_ascii=False))
