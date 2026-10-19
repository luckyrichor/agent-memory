"""Normalize already downloaded public corpora; raw and derived text never enter Git."""

import argparse
import json
import subprocess
from collections import Counter
from pathlib import Path

from agent_memory.evals.datasets import (
    conversation_split,
    dulemon,
    file_hash,
    locomo,
    longmemeval,
    perltqa,
    validate_evidence,
)

parser = argparse.ArgumentParser()
parser.add_argument("--root", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
if ".local" not in args.output.resolve().parts:
    parser.error("corpus output must be in ignored .local/")
args.output.mkdir(parents=True, exist_ok=False)
r = args.root
sources = {
    "longmemeval_oracle": (
        [r / "longmemeval_oracle.json"],
        lambda: longmemeval(r / "longmemeval_oracle.json"),
        "MIT",
        "https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned",
    ),
    "longmemeval_s": (
        [r / "longmemeval_s_cleaned.json"],
        lambda: longmemeval(r / "longmemeval_s_cleaned.json"),
        "MIT",
        "https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned",
    ),
    "locomo": (
        [r / "locomo/data/locomo10.json"],
        lambda: locomo(r / "locomo/data/locomo10.json"),
        "CC-BY-NC-4.0",
        "https://github.com/snap-research/locomo",
    ),
    "perltqa_zh": (
        [r / "PerLTQA/Dataset/zh/perltmem.json", r / "PerLTQA/Dataset/zh/perltqa.json"],
        lambda: perltqa(
            r / "PerLTQA/Dataset/zh/perltmem.json", r / "PerLTQA/Dataset/zh/perltqa.json"
        ),
        "CC-BY-NC-4.0",
        "https://github.com/Elvin-Yiming-Du/PerLTQA",
    ),
    "dulemon": (
        [r / "DuLeMon.zip"],
        lambda: dulemon(r / "DuLeMon.zip"),
        "parent repository Apache-2.0; archive has no separate license",
        "https://github.com/PaddlePaddle/Research/tree/master/NLP/ACL2022-DuLeMon",
    ),
}
manifest = []
for name, (files, load, license_name, url) in sources.items():
    out = args.output / f"{name}.jsonl"
    counts = Counter()
    ids = []
    missing = []
    with out.open("w") as stream:
        for conv in load():
            ids.append(conv.conversation_id)
            counts["conversations"] += 1
            counts["documents"] += len(conv.documents)
            counts["questions"] += len(conv.questions)
            counts.update({"type:" + q.category: 1 for q in []})
            for q in conv.questions:
                counts["type:" + q.category] += 1
            invalid = validate_evidence(conv)
            if invalid:
                missing.append(
                    {"conversation_id": conv.conversation_id, "unresolved_reference_ids": invalid}
                )
            stream.write(conv.model_dump_json() + "\n")
    splits = conversation_split(ids)
    splitfile = args.output / f"{name}-split.json"
    splitfile.write_text(json.dumps(splits, indent=2))
    item = {
        "dataset": name,
        "source_url": url,
        "license": license_name,
        "raw_files": [
            {"name": p.name, "bytes": p.stat().st_size, "sha256": file_hash(p)} for p in files
        ],
        "normalized_sha256": file_hash(out),
        "split_sha256": file_hash(splitfile),
        "split_counts": {k: len(v) for k, v in splits.items()},
        "seed": 42,
        "counts": dict(counts),
        "unresolved_evidence": missing,
        "scope": "public corpus normalization only; no system quality run",
    }
    repo = r / ("locomo" if name == "locomo" else "PerLTQA")
    if name in ["locomo", "perltqa_zh"]:
        item["source_commit"] = subprocess.check_output(
            ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True
        ).strip()
    manifest.append(item)
    print(name, dict(counts), "unresolved_conversations", len(missing), flush=True)
(args.output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
