"""Independent blind audit of unreviewed joint keeps, without altering frozen labels."""

import csv
import json
import math
import random
import re
from collections import Counter
from pathlib import Path
from typing import Any

from agent_memory.evals.datasets import file_hash
from agent_memory.evals.human_review import answers, csv_text, digest
from agent_memory.evals.labeling import load_labels

FIELDS = (
    "item_id",
    "conversation_id",
    "subject",
    "candidate",
    "source",
    "record_sha256",
    "human_label",
    "human_reason",
)


def topic(text: str) -> str:
    """Descriptive rule buckets, never an annotation or reviewer-visible hint."""
    if re.search(r"喜欢|爱好|偏好|最爱|讨厌|爱吃", text):
        return "preference"
    if re.search(r"住|家乡|来自|城市|地址", text):
        return "residence-origin"
    if re.search(r"工作|职业|学生|毕业|上学|学习", text):
        return "work-education"
    if re.search(r"父|母|爸|妈|孩子|儿子|女儿|结婚|丈夫|妻子", text):
        return "family"
    return "other"


def prepare_joint_audit(
    *,
    items: Path,
    left: Path,
    right: Path,
    prior_human: Path,
    output: Path,
    seed: int = 20261022,
    sample_size: int = 72,
) -> dict[str, Any]:
    if ".local" not in output.resolve().parts:
        raise ValueError("private audit output required")
    rows = {r["item_id"]: r for r in map(json.loads, items.read_text().splitlines())}
    a, b, human = load_labels(left), load_labels(right), load_labels(prior_human)
    if rows.keys() != a.keys() or rows.keys() != b.keys() or not human.keys() <= rows.keys():
        raise ValueError("frozen coverage mismatch")
    joint = {k for k in rows if a[k].label == b[k].label == "keep"}
    rejected = {k for k in joint if k in human and human[k].label != "keep"}
    remaining = joint - rejected
    eligible = remaining - human.keys()
    if not 0 < sample_size <= len(eligible):
        raise ValueError("insufficient independent unreviewed candidates")
    rng = random.Random(seed)
    selected = rng.sample(sorted(eligible), sample_size)
    rng.shuffle(selected)
    blind = []
    mapping = {}
    for original in selected:
        alias = f"{rng.getrandbits(128):032x}"
        row = {**rows[original], "item_id": alias}
        row.update(human_label=None, human_reason=None)
        blind.append(row)
        mapping[alias] = original
    if len(mapping) != sample_size:
        raise ValueError("opaque ID collision")
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    template = output / "audit-blind.jsonl"
    template.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in blind))
    csv_path = output / "audit-blind.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        for row in blind:
            writer.writerow(
                {
                    k: ""
                    if k.startswith("human_")
                    else (digest(row) if k == "record_sha256" else csv_text(row[k]))
                    for k in FIELDS
                }
            )
    (output / "opaque-map-private.json").write_text(json.dumps(mapping, indent=2) + "\n")
    result = {
        "seed": seed,
        "joint_keep": len(joint),
        "owner_rejected_removed": len(rejected),
        "remaining_pool": len(remaining),
        "prior_reviewed_in_remaining_pool": len(remaining & human.keys()),
        "eligible_unreviewed_pool": len(eligible),
        "sample": len(selected),
        "previous_review_overlap": len(set(selected) & human.keys()),
        "conversations": len({rows[k]["conversation_id"] for k in selected}),
        "source_counts": dict(Counter(rows[k]["conversation_id"].split(":")[0] for k in selected)),
        "topic_counts": dict(Counter(topic(rows[k]["candidate"]) for k in selected)),
        "topic_rule": "descriptive regex, first matching category; not human/model labels; absent from reviewer table",
        "maximum_errors": 3,
        "human_completed": False,
        "passed": None,
        "error_rate": None,
        "confidence_interval_95": None,
        "format_approved": True,
        "format_authorization": "owner message om_x100b62bf9ec420a0c1f4c8e945cc40e",
        "files": {p.name: file_hash(p) for p in sorted(output.iterdir())},
        "inputs": {str(p): file_hash(p) for p in (items, left, right, prior_human)},
    }
    (output / "manifest.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return result


def hypergeometric_interval(errors: int, sample: int, population: int) -> tuple[int, int]:
    """Equal-tailed exact finite-population error-count interval at 95%."""
    if not 0 <= errors <= sample <= population or sample == 0:
        raise ValueError("valid finite sample required")

    def probability(k: int, total_errors: int) -> float:
        if not max(0, sample - (population - total_errors)) <= k <= min(sample, total_errors):
            return 0.0
        return (
            math.comb(total_errors, k)
            * math.comb(population - total_errors, sample - k)
            / math.comb(population, sample)
        )

    allowed = []
    for total in range(errors, population - sample + errors + 1):
        lower = sum(probability(k, total) for k in range(errors + 1))
        upper = sum(probability(k, total) for k in range(errors, sample + 1))
        if lower >= 0.025 and upper >= 0.025:
            allowed.append(total)
    return min(allowed), max(allowed)


def finalize_joint_audit(
    pack: Path, submitted: Path, output: Path, reviewer: str
) -> dict[str, Any]:
    if ".local" not in output.resolve().parts or not reviewer.strip():
        raise ValueError("private output and explicit owner identity required")
    manifest = json.loads((pack / "manifest.json").read_text())
    for name, sha in manifest["files"].items():
        if file_hash(pack / name) != sha:
            raise ValueError("frozen audit pack changed")
    for path, sha in manifest["inputs"].items():
        if file_hash(Path(path)) != sha:
            raise ValueError("frozen audit input changed")
    checked = answers(pack / "audit-blind.jsonl", submitted)
    if len(checked) != manifest["sample"]:
        raise ValueError("complete owner review required")
    errors = sum(row.label != "keep" for row in checked.values())
    lo, hi = hypergeometric_interval(errors, len(checked), manifest["eligible_unreviewed_pool"])
    result = {
        "sample": len(checked),
        "errors": errors,
        "error_rate": errors / len(checked),
        "passed": errors <= manifest["maximum_errors"],
        "maximum_errors": manifest["maximum_errors"],
        "error_count_population_95": [lo, hi],
        "error_rate_population_95": [
            lo / manifest["remaining_pool"],
            hi / manifest["remaining_pool"],
        ],
        "ci_method": "exact equal-tailed hypergeometric for unreviewed pool, previously confirmed keeps are known correct; not a new CI-upper-bound gate",
        "reviewer": reviewer,
        "submitted_sha256": file_hash(submitted),
        "phase1_accepted": False,
        "frozen_data_changed": False,
    }
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    (output / "report.json").write_text(json.dumps(result, indent=2) + "\n")
    (output / "human-labels-private.jsonl").write_text(
        "".join(x.model_dump_json() + "\n" for x in checked.values())
    )
    return result
