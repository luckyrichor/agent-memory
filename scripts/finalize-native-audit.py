"""Consume the owner's unchanged 230-row return; never synthesize review answers."""

import argparse
import json
from pathlib import Path

from agent_memory.evals.native_audit import finalize_native_audit

p = argparse.ArgumentParser()
for name in ("items", "references", "pack", "submitted", "output"):
    p.add_argument("--" + name, type=Path, required=True)
p.add_argument("--reviewer", required=True)
a = p.parse_args()
print(json.dumps(finalize_native_audit(**vars(a))))
