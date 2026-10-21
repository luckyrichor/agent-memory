"""Small independent hard-set controls with the existing synthetic pair, never frozen relabels."""

import asyncio
import json
import random
from pathlib import Path
from agent_memory.evals.annotate import annotate
from agent_memory.evals.datasets import file_hash

ROOT = Path(".local/phase1/round3/owner-hardset")
HARD = ROOT / "synthetic-hard-v1-final"


def read(p):
    return [json.loads(s) for s in p.read_text().splitlines()]


async def main():
    output = ROOT / "controls-probe"
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    items = {x["item_id"]: x for x in read(HARD / "items.jsonl")}
    truth = read(HARD / "constructor-truth-private.jsonl")
    rng = random.Random(20261021)
    selected = []
    for kind in sorted({x["kind"] for x in truth}):
        for length in (6, 9):
            pool = sorted(
                (
                    x["item_id"]
                    for x in truth
                    if x["kind"] == kind and len(items[x["item_id"]]["source"]) == length
                )
            )
            selected.extend(rng.sample(pool, 2))
    controls = {x["item_id"]: x for x in read(HARD / "controls.jsonl")}
    links = [x for x in read(HARD / "control-truth-private.jsonl") if x["base_item_id"] in selected]
    rows = [items[k] for k in selected] + [controls[x["item_id"]] for x in links]
    rng.shuffle(rows)
    path = output / "items-blind.jsonl"
    path.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in rows))
    freeze = json.loads(Path(".local/phase1/round3/closeout/synthetic-freeze.json").read_text())
    prompt = Path("docs/evals/prompts/annotation-v5.txt")
    assert file_hash(prompt) == freeze["prompt_sha256"]
    result = {
        "seed": 20261021,
        "scope": "exploratory controls only, no human quality evidence",
        "sample_base": len(selected),
        "sample_total": len(rows),
        "items_sha256": file_hash(path),
        "models": [],
    }
    for entry in freeze["models"]:
        model = entry["model"]
        dest = output / model
        try:
            await annotate(
                path,
                dest,
                prompt,
                model=model,
                batch_size=16,
                cache=output / "cache",
                interval=0.6,
                deduplicate_sources=True,
                compact_ids=True,
            )
            status = "complete"
        except Exception as e:
            status = type(e).__name__
        result["models"].append({"model": model, "provider": entry["provider"], "status": status})
        (output / "run.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result))


asyncio.run(main())
