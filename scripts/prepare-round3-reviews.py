"""ECD provisional negatives and owner-only conversation annotation; no new model calls."""

import argparse
import csv
import json
import random
import re
import shutil
from collections import Counter
from pathlib import Path

from agent_memory.evals.datasets import file_hash
from agent_memory.evals.human_review import csv_text, digest
from agent_memory.evals.labeling import load_labels


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path(".local/phase1/round3/reviews"))
    args = parser.parse_args()
    output = args.output
    if ".local" not in output.resolve().parts:
        parser.error("raw reviews must stay private .local")
    output.mkdir(parents=True, exist_ok=False)
    output.chmod(0o700)
    data = Path(".local/phase1/chinese-expansion-v2")
    frozen = Path(".local/phase1/chinese-guide-v2-full-fallback-resume1")
    rows = [json.loads(s) for s in (data / "ecd/items.jsonl").read_text().splitlines()]
    models = ["deepseek-v4-pro", "mimo-v2.6-flash"]
    labels = [
        load_labels(frozen / "ecd" / ("labels-" + m + "-run1") / "labels.jsonl") for m in models
    ]
    assert all(set(m) == {r["item_id"] for r in rows} for m in labels)
    negative = [r for r in rows if all(m[r["item_id"]].label == "discard" for m in labels)]
    (output / "ecd-negative-local.jsonl").write_text(
        "".join(
            json.dumps(
                {**r, "reference": "provisional_discard", "human_verified": False},
                ensure_ascii=False,
            )
            + "\n"
            for r in negative
        )
    )
    groups = {r["conversation_id"]: r["source"] for r in rows}
    split = json.loads((data / "ecd/split.json").read_text())
    pattern = re.compile(
        r"(我|本人|我们).{0,12}(住|岁|喜欢|工作|职业|地址|过敏|身高|体重|孩子|宝宝|孕|码|穿|皮肤|敏感|买过|买了|尺寸)"
    )
    strata = {"personal_information_hint": [], "no_personal_information_hint": []}
    for cid, source in sorted(groups.items()):
        key = (
            "personal_information_hint"
            if pattern.search(" ".join(x["text"] for x in source))
            else "no_personal_information_hint"
        )
        strata[key].append(cid)
    rng = random.Random(42)
    selected = {}
    # Take all scarce hint-positive conversations up to half; fill remainder from no-hint.
    hint_n = min(60, len(strata["personal_information_hint"]))
    for name, n in [
        ("personal_information_hint", hint_n),
        ("no_personal_information_hint", 120 - hint_n),
    ]:
        selected[name] = rng.sample(sorted(strata[name]), n)
    manual = []
    for stratum, ids in selected.items():
        for cid in ids:
            row = {
                "conversation_id": cid,
                "stratum": stratum,
                "source": groups[cid],
                "split": "dev" if cid in split["dev"] else "test",
                "human_memories": None,
                "human_no_memories": None,
                "human_reason": None,
            }
            row["record_sha256"] = digest(row)
            manual.append(row)
    rng.shuffle(manual)
    (output / "ecd-manual-120.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in manual)
    )
    fields = [
        "conversation_id",
        "stratum",
        "split",
        "source",
        "record_sha256",
        "human_memories",
        "human_no_memories",
        "human_reason",
    ]
    with (output / "ecd-manual-120.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for r in manual:
            writer.writerow({k: "" if k.startswith("human_") else csv_text(r[k]) for k in fields})
    audit = frozen / "human-review-v1/dulemon-native-reference"
    for name in ["audit-blind.csv", "audit-blind.jsonl", "reference-review.json"]:
        (output / "dulemon-native-reference").mkdir(exist_ok=True)
        shutil.copyfile(audit / name, output / "dulemon-native-reference" / name)
    audit_count = len((audit / "audit-blind.jsonl").read_text().splitlines())
    assert audit_count == 230
    negative_ids = {r["item_id"] for r in negative}
    complete_negative = sum(
        all(r["item_id"] in negative_ids for r in rows if r["conversation_id"] == cid)
        for cid in groups
    )
    report = {
        "seed": 42,
        "ecd_conversations": len(groups),
        "ecd_candidates": len(rows),
        "ecd_provisional_negative_candidates": len(negative),
        "ecd_provisional_entire_negative_conversations": complete_negative,
        "human_verified": False,
        "ecd_kappa_gate_applicable": False,
        "ecd_manual_conversations": len(manual),
        "ecd_strata_population": {k: len(v) for k, v in strata.items()},
        "ecd_manual_strata": dict(Counter(r["stratum"] for r in manual)),
        "ecd_manual_split": dict(Counter(r["split"] for r in manual)),
        "strata_limit": "regex personal-info hint only; anonymous speakers, not verified user facts or gold. Owner labels attribution.",
        "source_items_sha256": file_hash(data / "ecd/items.jsonl"),
        "labels_sha256": [
            file_hash(frozen / "ecd" / ("labels-" + m + "-run1") / "labels.jsonl") for m in models
        ],
        "required_owner_audit": audit_count,
        "ecd_manual_required_now": False,
        "other_old_reviews_required_now": False,
        "frozen_native_audit_unchanged": file_hash(audit / "audit-blind.jsonl")
        == file_hash(output / "dulemon-native-reference/audit-blind.jsonl"),
        "output_files_sha256": {
            str(p.relative_to(output)): file_hash(p) for p in output.rglob("*") if p.is_file()
        },
        "source_models": models,
        "phase_gate_passed": False,
    }
    (output / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {
                k: report[k]
                for k in [
                    "ecd_provisional_negative_candidates",
                    "ecd_provisional_entire_negative_conversations",
                    "ecd_manual_conversations",
                    "ecd_manual_strata",
                    "required_owner_audit",
                ]
            }
        )
    )


if __name__ == "__main__":
    main()
