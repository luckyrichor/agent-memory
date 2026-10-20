"""Owner-only review of native corpus references, independent of model selection."""

import argparse
import csv
import json
import random
from pathlib import Path
from typing import Any

from agent_memory.evals.datasets import file_hash
from agent_memory.evals.human_review import answers, csv_text, digest
from agent_memory.evals.labeling import load_labels


def make_reference_pack(
    items: Path,
    references: Path,
    output: Path,
    *,
    models: tuple[Path, Path] | None = None,
) -> dict[str, Any]:
    rows = [json.loads(s) for s in items.read_text().splitlines() if s]
    ids = [r["item_id"] for r in rows]
    ref = load_labels(references)
    if len(ids) != len(set(ids)) or set(ids) != ref.keys():
        raise ValueError("reference coverage mismatch")
    conflict = set()
    if models:
        a, b = (load_labels(p) for p in models)
        if a.keys() != ref.keys() or b.keys() != ref.keys():
            raise ValueError("model/reference coverage mismatch")
        conflict = {
            key
            for key in ids
            if a[key].label != ref[key].label
            or b[key].label != ref[key].label
            or a[key].label == "uncertain"
            or b[key].label == "uncertain"
        }
    audit = set(random.Random(42).sample(sorted(ids), k=(len(ids) + 9) // 10))
    output.mkdir(parents=True, exist_ok=False)
    output.chmod(0o700)
    for name, wanted in (("arbitration", conflict), ("audit", audit)):
        selected = [
            {**row, "human_label": None, "human_reason": None}
            for row in rows
            if row["item_id"] in wanted
        ]
        (output / f"{name}-blind.jsonl").write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in selected)
        )
        export_csv(output / f"{name}-blind.jsonl")
    provenance = {
        "items_sha256": file_hash(items),
        "references_sha256": file_hash(references),
        "models_sha256": [file_hash(p) for p in models] if models else [],
    }
    result = {
        "kind": "native-reference-review",
        "provenance": provenance,
        "items": len(ids),
        "arbitration_count": len(conflict),
        "audit_count": len(audit),
        "audit_seed": 42,
        "audit_fraction": 0.1,
        "human_threshold": 0.95,
        "arbitration_ids": sorted(conflict),
        "audit_ids": sorted(audit),
        "reference_authority": "Original corpus labels, not filtered by model keep votes",
        "human_review_complete": False,
        "human_agreement": None,
        "phase_gate_passed": False,
    }
    (output / "reference-review.json").write_text(json.dumps(result, indent=2))
    return result


def export_csv(template: Path) -> None:
    fields = [
        "item_id",
        "conversation_id",
        "subject",
        "candidate",
        "source",
        "record_sha256",
        "human_label",
        "human_reason",
    ]
    with template.with_suffix(".csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for line in template.read_text().splitlines():
            row = json.loads(line)
            output = {k: csv_text(row.get(k, "")) for k in fields[:5]}
            output.update(record_sha256=digest(row), human_label="", human_reason="")
            writer.writerow(output)


def finalize_reference(
    *,
    items: Path,
    references: Path,
    pack: Path,
    arbitration: Path,
    audit: Path,
    reviewer: str,
    output: Path,
    model_left: Path | None = None,
    model_right: Path | None = None,
) -> dict[str, Any]:
    """Consume real owner files; never called by dataset preparation/reporting."""
    if not reviewer.strip():
        raise ValueError("owner identity required")
    manifest = json.loads((pack / "reference-review.json").read_text())
    provenance = manifest["provenance"]
    if provenance["items_sha256"] != file_hash(items) or provenance[
        "references_sha256"
    ] != file_hash(references):
        raise ValueError("frozen source/reference changed")
    original_rows = list(map(json.loads, items.read_text().splitlines()))
    rows = {r["item_id"]: r for r in original_rows}
    ref = load_labels(references)
    if len(rows) != len(original_rows) or rows.keys() != ref.keys():
        raise ValueError("reference coverage changed")
    if (model_left is None) != (model_right is None):
        raise ValueError("both model inputs required together")
    models = (model_left, model_right) if model_left and model_right else None
    actual_model_hashes = [file_hash(p) for p in models] if models else []
    if actual_model_hashes != provenance["models_sha256"]:
        raise ValueError("frozen model labels changed or omitted")
    expected_conflicts = set()
    if models:
        a, b = (load_labels(p) for p in models)
        if a.keys() != rows.keys() or b.keys() != rows.keys():
            raise ValueError("model/reference coverage mismatch")
        expected_conflicts = {
            key
            for key in rows
            if a[key].label != ref[key].label
            or b[key].label != ref[key].label
            or a[key].label == "uncertain"
            or b[key].label == "uncertain"
        }
    for task in ("arbitration", "audit"):
        for line in (pack / f"{task}-blind.jsonl").read_text().splitlines():
            row = json.loads(line)
            if {k: v for k, v in row.items() if not k.startswith("human_")} != rows.get(
                row["item_id"]
            ):
                raise ValueError("frozen template changed")
    decisions = answers(pack / "arbitration-blind.jsonl", arbitration)
    checked = answers(pack / "audit-blind.jsonl", audit)
    expected_audit = set(random.Random(42).sample(sorted(rows), k=(len(rows) + 9) // 10))
    if (
        decisions.keys() != expected_conflicts
        or set(manifest["arbitration_ids"]) != expected_conflicts
        or checked.keys() != expected_audit
    ):
        raise ValueError("owner review coverage mismatch")
    before = {key: decisions.get(key, ref[key]) for key in rows}
    matches = sum(before[key].label == label.label for key, label in checked.items())
    ratio = matches / len(checked) if checked else None
    result = {
        "reviewer": reviewer,
        "human_review_complete": True,
        "audit_count": len(checked),
        "human_agreement": ratio,
        "human_consistency_passed": ratio is not None and ratio >= 0.95,
        "owner_approved_threshold": 0.95,
        "reference_before_audit_corrections": True,
        "phase_gate_passed": False,
        "provenance": provenance,
    }
    output.mkdir(parents=True, exist_ok=False)
    output.chmod(0o700)
    after = {**before, **checked}
    for name, labels in (("before-audit", before), ("after-audit", after)):
        (output / f"{name}.jsonl").write_text(
            "".join(labels[key].model_dump_json() + "\n" for key in rows)
        )
    (output / "report.json").write_text(json.dumps(result, indent=2))
    return result


def main() -> None:
    p = argparse.ArgumentParser()
    for name in ("items", "references", "pack", "arbitration", "audit", "output"):
        p.add_argument("--" + name, type=Path, required=True)
    p.add_argument("--reviewer", required=True)
    p.add_argument("--model-left", type=Path)
    p.add_argument("--model-right", type=Path)
    args = p.parse_args()
    if ".local" not in args.output.resolve().parts:
        p.error("human results must stay in .local/")
    print(json.dumps(finalize_reference(**vars(args)), ensure_ascii=False))


if __name__ == "__main__":
    main()
