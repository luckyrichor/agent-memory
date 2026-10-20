"""Freeze a qualified replacement pair, then annotate each fixed dataset in full."""

import asyncio
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(".local/phase1/chinese-rotation-v1")
DATA = Path(".local/phase1/chinese-expansion-v2")
PAIR = (
    ("deepseek-v4-pro-202606", "DeepSeek", "preflight-deepseek"),
    ("glm-5.2", "Z.ai", "preflight-glm"),
)


def git_state():
    return (
        subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        bool(subprocess.check_output(["git", "status", "--porcelain"], text=True).strip()),
    )


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


async def main():
    if len({vendor for _, vendor, _ in PAIR}) != 2:
        raise ValueError("independent annotation vendors required")
    qualifications = []
    for model, vendor, directory in PAIR:
        path = ROOT / directory
        summary_path = path / (model + "-summary.json")
        while not summary_path.exists():
            await asyncio.sleep(3)
        summary = json.loads(summary_path.read_text())
        rows = json.loads((path / "progress.json").read_text())
        if (
            not summary["preflight_pass"]
            or len(rows) != 106
            or summary["format_n"] != 100
            or summary["format_valid"] < 99
            or not summary["consistent_5"]
            or not all(
                r.get("observed_disabled_thinking") and r.get("http_status") == 200 for r in rows
            )
        ):
            raise RuntimeError("replacement model preflight failed: " + model)
        qualifications.append(
            {
                "model": model,
                "vendor": vendor,
                "summary_sha256": sha(summary_path),
                "records_sha256": sha(path / "progress.json"),
            }
        )
    source_commit, dirty = await asyncio.to_thread(git_state)
    frozen = {
        "generated_at": datetime.now(UTC).isoformat(),
        "source_commit_before_run": source_commit,
        "working_tree_modified": dirty,
        "qualifications": qualifications,
        "batch_size": 50,
        "shards_per_dataset_model": 2,
        "compact_identifiers": True,
        "shared_sources": True,
        "prompt": "docs/evals/prompts/annotation-v4.txt",
        "prompt_sha256": sha(Path("docs/evals/prompts/annotation-v4.txt")),
        "data": {
            name: {
                "items_sha256": sha(DATA / name / "items.jsonl"),
                "split_sha256": sha(
                    DATA
                    / name
                    / ("source-frozen-split.json" if name == "dulemon" else "split.json")
                ),
            }
            for name in ("dulemon", "ecd")
        },
        "source_files": {str(p): sha(p) for p in Path("src/agent_memory/evals").glob("*.py")},
        "note": "New pair only, full datasets; old partial annotations never merged. Native references are not filtered by model votes. No human answers generated.",
    }
    with (ROOT / "frozen-run.json").open("x") as stream:
        json.dump(frozen, stream, indent=2)
    print(json.dumps({"frozen_models": [m for m, _, _ in PAIR]}), flush=True)

    async def annotate(name, model):
        destination = ROOT / name / ("labels-" + model + "-run1")
        destination.parent.mkdir(exist_ok=True)
        command = [
            "uv",
            "run",
            "python",
            "-m",
            "agent_memory.evals.annotate",
            "--items",
            str(DATA / name / "items.jsonl"),
            "--output",
            str(destination),
            "--cache",
            ".local/phase1/annotation-cache",
            "--model",
            model,
            "--prompt",
            frozen["prompt"],
            "--batch-size",
            "50",
            "--shards",
            "2",
            "--deduplicate-sources",
            "--compact-identifiers",
            "--retry-invalid-cache",
        ]
        with (destination.parent / (model + "-run1.log")).open("x") as log:
            process = await asyncio.create_subprocess_exec(
                *command, stdout=log, stderr=asyncio.subprocess.STDOUT
            )
            code = await process.wait()
        result = {
            "dataset": name,
            "model": model,
            "exit_code": code,
            "complete": (destination / "COMPLETE").exists(),
            "directory": str(destination),
        }
        print(json.dumps(result), flush=True)
        return result

    results = await asyncio.gather(
        *(annotate(name, model) for name in ("dulemon", "ecd") for model, _, _ in PAIR)
    )
    (ROOT / "annotation-results.json").write_text(json.dumps(results, indent=2))
    if not all(r["complete"] and r["exit_code"] == 0 for r in results):
        raise RuntimeError("replacement annotation incomplete; partial ledgers retained")


asyncio.run(main())
