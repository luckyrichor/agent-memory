"""Score owner-returned native-reference audit against the frozen, uncorrected labels."""

import json
import random
from pathlib import Path
from typing import Any

from agent_memory.evals.datasets import file_hash
from agent_memory.evals.human_review import answers
from agent_memory.evals.labeling import load_labels


def finalize_native_audit(
    *, items: Path, references: Path, pack: Path, submitted: Path, reviewer: str, output: Path
) -> dict[str, Any]:
    if not reviewer.strip() or ".local" not in output.resolve().parts:
        raise ValueError("owner identity and private output required")
    manifest = json.loads((pack / "reference-review.json").read_text())
    provenance = manifest["provenance"]
    if provenance["items_sha256"] != file_hash(items) or provenance[
        "references_sha256"
    ] != file_hash(references):
        raise ValueError("frozen source/reference changed")
    rows = {r["item_id"]: r for r in map(json.loads, items.read_text().splitlines())}
    ref = load_labels(references)
    if rows.keys() != ref.keys():
        raise ValueError("native reference coverage mismatch")
    expected = set(random.Random(42).sample(sorted(rows), (len(rows) + 9) // 10))
    template = pack / "audit-blind.jsonl"
    raw = [json.loads(line) for line in template.read_text().splitlines()]
    for row in raw:
        frozen = {k: v for k, v in row.items() if not k.startswith("human_")}
        if frozen != rows.get(row["item_id"]):
            raise ValueError("audit source changed")
    if {r["item_id"] for r in raw} != expected or set(manifest["audit_ids"]) != expected:
        raise ValueError("frozen sampling changed")
    checked = answers(template, submitted)
    if checked.keys() != expected:
        raise ValueError("owner audit incomplete")
    matches = sum(label.label == ref[key].label for key, label in checked.items())
    ratio = matches / len(checked)
    passed = ratio >= 0.95
    # Do not first correct references and then manufacture a 100% consistency rate.
    adopted = {**ref, **checked} if passed else checked
    positives = [key for key, label in adopted.items() if label.label == "keep"]
    result = {
        "reviewer": reviewer,
        "frozen_reference_agreement": ratio,
        "matches": matches,
        "audit_count": len(checked),
        "threshold": 0.95,
        "native_reference_accepted": passed,
        "gold_basis": "native-after-owner-corrections" if passed else "human-confirmed-subset-only",
        "usable_positive_memory_points": len(positives),
        "human_positive_memory_points": sum(l.label == "keep" for l in checked.values()),
        "submitted_sha256": file_hash(submitted),
        "references_sha256": file_hash(references),
        "phase_gate_passed": False,
    }
    output.mkdir(parents=True, exist_ok=False)
    output.chmod(0o700)
    (output / "adopted-labels.jsonl").write_text(
        "".join(adopted[k].model_dump_json() + "\n" for k in sorted(adopted))
    )
    (output / "report.json").write_text(json.dumps(result, indent=2) + "\n")
    return result
