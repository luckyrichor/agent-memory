"""Run a command with the approved phase1 Ark runtime model, without persisting keys.

Usage: with-ark uv run python scripts/with-phase1-runtime.py COMMAND [ARGS ...]
Does not start or restart any service by itself. Existing B0 artifacts stay frozen.
"""

import json
import os
import sys
from pathlib import Path

if len(sys.argv) < 2:
    raise SystemExit("usage: with-ark uv run python scripts/with-phase1-runtime.py COMMAND [ARGS]")
if not os.environ.get("ARK_API_KEY"):
    raise SystemExit("shared Ark credential missing; invoke through with-ark")
profile = json.loads(
    (Path(__file__).resolve().parents[1] / "docs/evals/model-roles-v3.json").read_text()
)["runtime_extraction"]
child_env = dict(os.environ)
child_env.update(
    MEMORY_EXTRACTION_MODEL=profile["model"],
    MEMORY_EXTRACTION_ENDPOINT=profile["endpoint"],
    MEMORY_EXTRACTION_TOKEN=os.environ["ARK_API_KEY"],
    MEMORY_EXTRACTION_TRUST_ENV="false",
)
os.execvpe(sys.argv[1], sys.argv[1:], child_env)
