"""Prepare append-only phase1 datasets; safe aggregate-only stdout."""

import argparse
import json
import subprocess
from pathlib import Path

from agent_memory.evals.chinese_expansion import (
    diagnose,
    dulemon,
    ecd,
    frozen_extension,
    inherit_source_split,
    perltqa,
    read_jsonl,
    write_jsonl,
)
from agent_memory.evals.datasets import file_hash

p = argparse.ArgumentParser()
p.add_argument("--output", type=Path, required=True)
p.add_argument("--dulemon-count", type=int, default=400)
p.add_argument("--ecd-count", type=int, default=400)
a = p.parse_args()
if ".local" not in a.output.resolve().parts:
    p.error("source data must stay under ignored .local/")
a.output.mkdir(parents=True, exist_ok=False)
a.output.chmod(0o700)
root = Path(".local/phase1")
data = root / "data"
diagnostic = diagnose(
    root / "public-chinese-v1/items.jsonl",
    root / "public-labels-glm-v4/labels.jsonl",
    root / "public-labels-deepseekpro-v4-shards4/labels.jsonl",
)
(a.output / "diagnosis.json").write_text(json.dumps(diagnostic, ensure_ascii=False, indent=2))
old = {r["item_id"]: r for r in read_jsonl(root / "public-chinese-v1/items.jsonl")}
# Examples stay in the restricted attachment, never source text in Git reports.
examples = []
for category, bucket in diagnostic["categories"].items():
    for key in bucket["example_ids"]:
        examples.append({"category": category, **old[key]})
write_jsonl(a.output / "diagnostic-examples-local.jsonl", examples)

results = {}
results["dulemon"] = dulemon(
    data / "DuLeMon.zip",
    root / "public-chinese-v1/items.jsonl",
    a.output / "dulemon",
    count=a.dulemon_count,
)
old_split = json.loads((root / "public-chinese-v1/split.json").read_text())
new_ids = [r["conversation_id"] for r in read_jsonl(a.output / "dulemon/corpus.jsonl")]
split = frozen_extension(old_split, new_ids)
(a.output / "dulemon/split.json").write_text(json.dumps(split, indent=2))
results["dulemon"]["frozen_previous_split_sha256"] = file_hash(
    root / "public-chinese-v1/split.json"
)
results["dulemon"]["new_split_counts"] = {
    name: len(split[name]) - len(old_split[name]) for name in split
}
source_split_path = root / "normalized-v3/dulemon-split.json"
aliases = {
    f"dulemon-both-train:{i:04d}": f"dulemon:DuLeMon/both/train.json:{i}"
    for i in results["dulemon"]["new_indices"]
}
inherited = inherit_source_split(json.loads(source_split_path.read_text()), aliases)
(a.output / "dulemon/source-frozen-split.json").write_text(json.dumps(inherited, indent=2))
results["dulemon"]["evaluation_split"] = "source-frozen-split.json"
results["dulemon"]["source_frozen_split_sha256"] = file_hash(source_split_path)
results["dulemon"]["source_frozen_split_counts"] = {
    side: len(ids) for side, ids in inherited.items()
}
results["dulemon"]["split_note"] = (
    "Native source split inherited; split.json is an unused historical-review append-only projection, never used for evaluation. Do not combine historical subset scores across namespaces."
)
results["perltqa"] = perltqa(
    data / "PerLTQA/Dataset/zh/perltmem.json",
    data / "PerLTQA/Dataset/zh/perltqa.json",
    a.output / "perltqa",
)
results["perltqa"]["source_commit"] = subprocess.check_output(
    ["git", "-C", str(data / "PerLTQA"), "rev-parse", "HEAD"], text=True
).strip()
results["ecd"] = ecd(data / "ECD.zip", a.output / "ecd", count=a.ecd_count)
for name, result in results.items():
    directory = a.output / name
    result["files"] = {f.name: file_hash(f) for f in sorted(directory.iterdir()) if f.is_file()}
    (directory / "manifest.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(
        json.dumps(
            {
                "dataset": name,
                "conversations": result["conversations"],
                "candidates": result.get("candidates", result.get("native_memory_records")),
                "real_chinese_eligible": not result["synthetic"],
            }
        ),
        flush=True,
    )
(a.output / "manifest.json").write_text(json.dumps(results, ensure_ascii=False, indent=2))
