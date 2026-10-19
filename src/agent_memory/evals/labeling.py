"""Human review is an explicit input, never supplied by the coding assistant."""

import hashlib
import json
import random
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from agent_memory.evals.metrics import agreement


class Label(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    item_id: str
    label: Literal["keep", "discard", "uncertain"]
    reason: str


def load_labels(path: Path) -> dict[str, Label]:
    labels = [
        Label.model_validate_json(line) for line in path.read_text().splitlines() if line.strip()
    ]
    mapped = {row.item_id: row for row in labels}
    if len(mapped) != len(labels):
        raise ValueError("duplicate label item ID")
    return mapped


def review_pack(items: Path, left: Path, right: Path, output: Path, *, seed: int = 42) -> None:
    a, b = load_labels(left), load_labels(right)
    rows = [json.loads(line) for line in items.read_text().splitlines() if line.strip()]
    ids = [str(row["item_id"]) for row in rows]
    if len(set(ids)) != len(ids) or set(ids) != a.keys() or a.keys() != b.keys():
        raise ValueError("item/annotation IDs do not exactly match")
    output.mkdir(parents=True, exist_ok=False)
    conflicts = {
        key
        for key in ids
        if a[key].label != b[key].label
        or a[key].label == "uncertain"
        or b[key].label == "uncertain"
    }
    rng = random.Random(seed)
    audit = set(rng.sample(sorted(ids), k=(len(ids) + 9) // 10))
    # The reviewer sees source and candidate only; never sees either model's label.
    for name, wanted in (("arbitration-blind.jsonl", conflicts), ("audit-blind.jsonl", audit)):
        (output / name).write_text(
            "".join(
                json.dumps({**row, "human_label": None, "human_reason": None}, ensure_ascii=False)
                + "\n"
                for row in rows
                if row["item_id"] in wanted
            )
        )
    result = agreement([a[key].label for key in ids], [b[key].label for key in ids])
    result.update(
        {
            "conflict_count": len(conflicts),
            "audit_count": len(audit),
            "seed": seed,
            "human_review_complete": False,
            "arbitration_ids": sorted(conflicts),
            "audit_ids": sorted(audit),
            "human_agreement": None,
            "items_sha256": hashlib.sha256(items.read_bytes()).hexdigest(),
        }
    )
    (output / "model-agreement.json").write_text(json.dumps(result, indent=2))
