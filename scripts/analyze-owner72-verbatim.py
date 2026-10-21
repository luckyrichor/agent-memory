"""Real owner audit, original-ID merge and offline literal-evidence filtering. No API calls."""

import argparse, csv, json, random, re
from collections import Counter, defaultdict
from pathlib import Path

from agent_memory.evals.approved_audit import FIELDS
from agent_memory.evals.datasets import file_hash
from agent_memory.evals.human_review import answers, csv_text, digest
from agent_memory.evals.metrics import ratio
from agent_memory.evals.verbatim_filter import VERSION, check_candidate

p = argparse.ArgumentParser()
p.add_argument("--output", type=Path, required=True)
a = p.parse_args()
if ".local" not in a.output.resolve().parts:
    p.error("private output required")
a.output.mkdir(parents=True, exist_ok=False, mode=0o700)


def read(p):
    return json.loads(Path(p).read_text())


def lines(p):
    return [json.loads(s) for s in Path(p).read_text().splitlines()]


def write(name, rows):
    (a.output / name).write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in rows))


pack = Path(".local/phase1/round3/approved-followup/joint-audit-72-v1")
submitted = Path(".local/dulemon72-final.csv")
checked = answers(pack / "audit-blind.jsonl", submitted)
mapping = read(pack / "opaque-map-private.json")
items_path = Path(".local/phase1/chinese-expansion-v2/dulemon/items.jsonl")
items = {r["item_id"]: r for r in lines(items_path)}
old_path = Path(".local/phase1/round3/owner-hardset/native-audit-final/adopted-labels.jsonl")
old = {r["item_id"]: r for r in lines(old_path)}
new = {
    mapping[k]: v.model_copy(update={"item_id": mapping[k]}).model_dump()
    for k, v in checked.items()
}
if old.keys() & new.keys():
    raise ValueError("new blind audit overlaps prior owner review")
merged = old | new
positives = {k: v for k, v in merged.items() if v["label"] == "keep"}
write("human-confirmed-labels.jsonl", [merged[k] for k in sorted(merged)])
write("human-positive-labels.jsonl", [positives[k] for k in sorted(positives)])
write("human-positive-items.jsonl", [items[k] for k in sorted(positives)])
with (a.output / "human-confirmed-positive.csv").open(
    "w", encoding="utf-8-sig", newline=""
) as stream:
    w = csv.DictWriter(stream, fieldnames=FIELDS)
    w.writeheader()
    for k in sorted(positives):
        row = items[k]
        w.writerow(
            {
                **{
                    name: csv_text(row[name])
                    for name in ("item_id", "conversation_id", "subject", "candidate", "source")
                },
                "record_sha256": digest(row),
                "human_label": "keep",
                "human_reason": positives[k]["reason"],
            }
        )
confusion = Counter()
error_types = Counter()
secondary = Counter()
decisions = []
groups = defaultdict(list)
for original, human in new.items():
    decision = check_candidate(items[original])
    supported = decision.status == "supported"
    confusion[(human["label"], supported)] += 1
    groups[items[original]["conversation_id"]].append(human["label"] == "keep")
    primary = None
    if human["label"] != "keep":
        reason = human["reason"]
        primary = (
            "assistant-attribution"
            if re.search("助手|称呼", reason)
            else "unsupported-detail-or-inference"
        )
        error_types[primary] += 1
        if re.search("没说|没提|未提|未出现|没依据|无法确定", reason):
            secondary["unsupported-detail-or-inference"] += 1
        if re.search("助手|称呼", reason):
            secondary["assistant-attribution"] += 1
    decisions.append(
        {
            "original_item_id": original,
            "human_label": human["label"],
            "human_reason": human["reason"],
            "error_primary": primary,
            **decision.to_dict(),
        }
    )
write("offline-decisions-private.jsonl", decisions)
pair = Path(".local/phase1/chinese-guide-v2-full-fallback-resume1/dulemon")
left_path = pair / "labels-deepseek-v4-pro-run1/labels.jsonl"
right_path = pair / "labels-mimo-v2.6-flash-run1/labels.jsonl"
left = {r["item_id"]: r["label"] for r in lines(left_path)}
right = {r["item_id"]: r["label"] for r in lines(right_path)}
joint = {k for k in left if left[k] == right[k] == "keep"}
owner_rejected = {k for k in joint if k in merged and merged[k]["label"] != "keep"}
remaining = joint - owner_rejected
pool_decisions = [
    {"original_item_id": k, **check_candidate(items[k]).to_dict()} for k in sorted(remaining)
]
write("pool-decisions-private.jsonl", pool_decisions)
supported = {r["original_item_id"] for r in pool_decisions if r["status"] == "supported"}
unseen = supported - merged.keys()
errors = sum(v["label"] != "keep" for v in new.values())
keeps = len(new) - errors
reject_errors = confusion[("discard", False)]
harm = confusion[("keep", False)]
precision = ratio([(sum(x), len(x)) for x in groups.values()]).to_dict()
previous = read(".local/phase1/round3/verbatim-filter/owner72-result/report.json")
assert previous["submitted_sha256"] == file_hash(submitted) and previous["errors"] == errors
rng = random.Random(20261023)
ordered = sorted(unseen)
rng.shuffle(ordered)
# This private list is not an audit sheet and does not claim n=72.
(a.output / "fresh-eligible-private.json").write_text(json.dumps(ordered, indent=2) + "\n")
summary = {
    "input_return_sha256": file_hash(submitted),
    "previous_gold": sum(v["label"] == "keep" for v in old.values()),
    "new_keep": keeps,
    "new_discard": errors,
    "overlap": len(old.keys() & new.keys()),
    "confirmed_positive_points": len(positives),
    "minimum": 700,
    "target": 1500,
    "minimum_gap": 700 - len(positives),
    "target_gap": 1500 - len(positives),
    "confirmed_positive_conversations": len({items[k]["conversation_id"] for k in positives}),
    "human_checked_items": len(merged),
    "audit_sample": len(new),
    "maximum_errors": 3,
    "passed": errors <= 3,
    "sample_precision_cluster_ci95": precision,
    "remaining_pool_error_count_exact_ci95": previous["error_count_population_95"],
    "remaining_pool_error_rate_exact_ci95": previous["error_rate_population_95"],
    "remaining_pool_precision_exact_ci95": [
        1 - previous["error_rate_population_95"][1],
        1 - previous["error_rate_population_95"][0],
    ],
    "primary_error_types": dict(error_types),
    "secondary_error_tags_overlapping": dict(secondary),
    "filter_version": VERSION,
    "offline_error_recall": {
        "numerator": reject_errors,
        "denominator": errors,
        "value": reject_errors / errors,
    },
    "offline_correct_harm": {"numerator": harm, "denominator": keeps, "value": harm / keeps},
    "offline_correct_retained": confusion[("keep", True)],
    "offline_validation_role": "development/tuning only; never acceptance evidence after fitting these rules",
    "filter_owner_approved": False,
    "offline_acceptance_claimed": False,
    "global_joint_keep": len(joint),
    "owner_rejected_in_joint": len(owner_rejected),
    "remaining_after_known_rejects": len(remaining),
    "filter_supported": len(supported),
    "filter_uncertain": len(remaining - supported),
    "fresh_unreviewed_supported": len(unseen),
    "fresh_sample_target": 72,
    "fresh_sample_deficit": max(0, 72 - len(unseen)),
    "fresh_seed": 20261023,
    "fresh_audit_created": False,
    "fresh_audit_blocker": "not enough independent unreviewed literal-supported items; no sampling with replacement or reusing development rows",
    "incremental_annotation_started": False,
    "model_calls": 0,
    "phase1_accepted": False,
    "phase2_started": False,
    "input_hashes": {
        str(x): file_hash(x)
        for x in (
            items_path,
            old_path,
            left_path,
            right_path,
            submitted,
            pack / "opaque-map-private.json",
        )
    },
    "files": {x.name: file_hash(x) for x in sorted(a.output.iterdir())},
}
(a.output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
print(
    json.dumps(
        {k: v for k, v in summary.items() if k not in ("files", "input_hashes")}, ensure_ascii=False
    )
)
