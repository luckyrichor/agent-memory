"""Validate real owner answers; calculate audit agreement before applying audit corrections."""

import csv
import hashlib
import json
import random
from pathlib import Path
from typing import Any

from agent_memory.evals.labeling import Label, load_labels


def digest(row: dict[str, Any]) -> str:
    original = {key: value for key, value in row.items() if not key.startswith("human_")}
    return hashlib.sha256(
        json.dumps(original, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


def csv_text(value: Any) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return "'" + text if text.startswith(("=", "+", "-", "@", "\t", "\r")) else text


def answers(template: Path, submitted: Path) -> dict[str, Label]:
    original = [json.loads(line) for line in template.read_text().splitlines() if line.strip()]
    expected = {row["item_id"]: row for row in original}
    if len(expected) != len(original):
        raise ValueError("duplicate template ID")
    is_csv = submitted.suffix.lower() == ".csv"
    if is_csv:
        with submitted.open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
    else:
        rows = [json.loads(line) for line in submitted.read_text().splitlines() if line.strip()]
    result = {}
    for row in rows:
        key = row.get("item_id")
        if not isinstance(key, str) or key not in expected or key in result:
            raise ValueError("human review ID coverage invalid")
        reference = expected[key]
        if is_csv:
            if row.get("record_sha256") != digest(reference):
                raise ValueError("human review frozen record hash mismatch")
            for field in ("item_id", "conversation_id", "subject", "candidate", "source"):
                if row.get(field, "") != csv_text(reference.get(field, "")):
                    raise ValueError("human review source/candidate was changed")
        else:
            frozen = {k: v for k, v in row.items() if not k.startswith("human_")}
            if frozen != {k: v for k, v in reference.items() if not k.startswith("human_")}:
                raise ValueError("human review source/candidate was changed")
        label, reason = row.get("human_label"), row.get("human_reason")
        if (
            label not in ("keep", "discard", "uncertain")
            or not isinstance(reason, str)
            or not reason.strip()
        ):
            raise ValueError("human review has missing or invalid owner answers")
        result[key] = Label.model_validate(
            {"item_id": key, "label": label, "reason": reason.strip()}
        )
    if result.keys() != expected.keys():
        raise ValueError("human review ID coverage invalid")
    return result


def finalize(
    *,
    items: Path,
    left: Path,
    right: Path,
    pack: Path,
    arbitration: Path,
    audit: Path,
    reviewer: str,
    threshold: float,
    output: Path,
) -> dict[str, Any]:
    if not reviewer.strip() or not 0 <= threshold <= 1:
        raise ValueError("explicit reviewer and valid owner-approved threshold required")
    provenance = json.loads((pack / "provenance.json").read_text())
    actual = {
        "items_sha256": hashlib.sha256(items.read_bytes()).hexdigest(),
        "labels_sha256": [hashlib.sha256(p.read_bytes()).hexdigest() for p in (left, right)],
    }
    if provenance != actual:
        raise ValueError("human review provenance does not match frozen labels")
    a, b = load_labels(left), load_labels(right)
    original_rows = [json.loads(line) for line in items.read_text().splitlines() if line.strip()]
    ids = [row["item_id"] for row in original_rows]
    frozen_items = {row["item_id"]: row for row in original_rows}
    if len(set(ids)) != len(ids) or set(ids) != a.keys() or a.keys() != b.keys():
        raise ValueError("frozen annotation ID coverage invalid")
    for task in ("arbitration", "audit"):
        for line in (pack / (task + "-blind.jsonl")).read_text().splitlines():
            template_row = json.loads(line)
            frozen = {k: v for k, v in template_row.items() if not k.startswith("human_")}
            if frozen != frozen_items.get(template_row.get("item_id")):
                raise ValueError("human template does not match frozen dataset")
    decisions = answers(pack / "arbitration-blind.jsonl", arbitration)
    checked = answers(pack / "audit-blind.jsonl", audit)
    conflicts = {key for key in ids if a[key].label != b[key].label or a[key].label == "uncertain"}
    if decisions.keys() != conflicts:
        raise ValueError("arbitration template does not match model conflicts")
    expected_audit = set(random.Random(42).sample(sorted(ids), k=(len(ids) + 9) // 10))
    if checked.keys() != expected_audit:
        raise ValueError("audit template does not match frozen seed42 sample")
    before = {key: decisions[key] if key in decisions else a[key] for key in ids}
    correct = sum(before[key].label == row.label for key, row in checked.items())
    consistency = correct / len(checked) if checked else None
    # Never replace reference labels with audit answers before calculating agreement.
    after = {**before, **checked}
    summary = {
        "reviewer": reviewer,
        "human_review_complete": True,
        "owner_approved_threshold": threshold,
        "audit_count": len(checked),
        "audit_matches_before_corrections": correct,
        "human_agreement": consistency,
        "human_consistency_passed": consistency is not None and consistency >= threshold,
        "arbitrated_count": len(decisions),
        "candidate_count": len(ids),
        "keep_after_audit": sum(row.label == "keep" for row in after.values()),
        "uncertain_after_audit": sum(row.label == "uncertain" for row in after.values()),
        "phase_gate_passed": False,
        "provenance": actual,
        "scope": "Owner answers supplied as files, no assistant-generated human labels. Other phase gates not evaluated.",
    }
    output.mkdir(parents=True, exist_ok=False)
    output.chmod(0o700)
    for name, labels in (("before-audit", before), ("after-audit", after)):
        (output / (name + ".jsonl")).write_text(
            "".join(labels[key].model_dump_json() + "\n" for key in ids)
        )
    (output / "report.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    return summary


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    for name in ("items", "left", "right", "pack", "arbitration", "audit", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--threshold", type=float, required=True)
    args = parser.parse_args()
    if ".local" not in args.output.resolve().parts:
        parser.error("raw human review output must stay under ignored .local/")
    print(json.dumps(finalize(**vars(args)), ensure_ascii=False))


if __name__ == "__main__":
    main()
