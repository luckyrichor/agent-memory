"""Diagnose dev labels and freeze a label-independent whole-conversation pilot."""

import argparse
import json
import random
from collections import Counter
from pathlib import Path

from agent_memory.evals.chinese_expansion import read_jsonl, write_jsonl
from agent_memory.evals.datasets import file_hash
from agent_memory.evals.labeling import load_labels
from agent_memory.evals.metrics import agreement

p = argparse.ArgumentParser()
p.add_argument("--output", type=Path, required=True)
args = p.parse_args()
data = Path(".local/phase1/chinese-expansion-v2")
previous = Path(".local/phase1/chinese-rotation-v2")
models = [
    r["model"] for r in json.loads((previous / "frozen-run.json").read_text())["qualifications"]
]
args.output.mkdir(parents=True, exist_ok=False)
summary = {
    "seed": 42,
    "minimum_candidates_per_source": 100,
    "selection": "dev only, whole conversations sampled independently of labels",
    "models": models,
    "datasets": {},
}
for name in ("dulemon", "ecd"):
    split_name = "source-frozen-split.json" if name == "dulemon" else "split.json"
    split_path = data / name / split_name
    split = json.loads(split_path.read_text())
    dev = set(split["dev"])
    rows = read_jsonl(data / name / "items.jsonl")
    eligible = [r for r in rows if r["conversation_id"] in dev]
    assert not dev.intersection(split["test"])
    labels = [
        load_labels(previous / name / ("labels-" + m + "-run1") / "labels.jsonl") for m in models
    ]
    matrix = Counter(
        (labels[0][r["item_id"]].label, labels[1][r["item_id"]].label) for r in eligible
    )
    reasons = Counter(
        (labels[0][r["item_id"]].reason, labels[1][r["item_id"]].reason)
        for r in eligible
        if labels[0][r["item_id"]].label != labels[1][r["item_id"]].label
    )
    groups = sorted({r["conversation_id"] for r in eligible})
    random.Random(42).shuffle(groups)
    selected = set()
    count = 0
    for group in groups:
        selected.add(group)
        count += sum(r["conversation_id"] == group for r in eligible)
        if count >= 100:
            break
    pilot = [r for r in eligible if r["conversation_id"] in selected]
    target = args.output / name
    target.mkdir()
    write_jsonl(target / "items.jsonl", pilot)
    (target / split_name).write_bytes(split_path.read_bytes())
    summary["datasets"][name] = {
        "source_items_sha256": file_hash(data / name / "items.jsonl"),
        "source_split_sha256": file_hash(split_path),
        "dev_candidates": len(eligible),
        "dev_label_matrix": {"/".join(k): v for k, v in sorted(matrix.items())},
        "dev_disagreement_reasons": {"/".join(k): v for k, v in sorted(reasons.items())},
        "pilot_conversations": sorted(selected),
        "pilot_candidates": len(pilot),
        "pilot_items_sha256": file_hash(target / "items.jsonl"),
        "previous_pilot_agreement": agreement(
            *[[model[r["item_id"]].label for r in pilot] for model in labels]
        ),
    }
(args.output / "selection.json").write_text(json.dumps(summary, indent=2))
print(
    json.dumps(
        {
            name: {
                k: v
                for k, v in values.items()
                if k in ("dev_candidates", "pilot_candidates", "previous_pilot_agreement")
            }
            for name, values in summary["datasets"].items()
        }
    )
)
