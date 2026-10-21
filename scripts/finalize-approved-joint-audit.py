"""Score a real complete owner return; never author human answers."""

import argparse, json
from pathlib import Path
from agent_memory.evals.approved_audit import finalize_joint_audit

p = argparse.ArgumentParser()
for name in ("pack", "submitted", "output"):
    p.add_argument("--" + name, type=Path, required=True)
p.add_argument("--reviewer", required=True)
a = p.parse_args()
print(json.dumps(finalize_joint_audit(**vars(a))))
