"""Build an owner-approved independent eight-column audit with no exposed model labels."""

import argparse, json
from pathlib import Path
from agent_memory.evals.approved_audit import prepare_joint_audit

p = argparse.ArgumentParser()
for name in ("items", "left", "right", "prior-human", "output"):
    p.add_argument("--" + name, type=Path, required=True)
p.add_argument("--seed", type=int, default=20261022)
a = p.parse_args()
print(json.dumps(prepare_joint_audit(**vars(a))))
