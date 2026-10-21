"""Generate independent hard fixtures; does not replace any frozen corpus or labels."""

import argparse
import json
from pathlib import Path
from agent_memory.evals.synthetic_hard import build_hardset

p = argparse.ArgumentParser()
p.add_argument("--output", type=Path, required=True)
p.add_argument("--seed", type=int, default=20261021)
a = p.parse_args()
print(json.dumps(build_hardset(a.output, seed=a.seed), ensure_ascii=False))
