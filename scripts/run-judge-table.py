"""Execute a frozen per-table pool. Stage1 uses only explicit synthetic preflight rows."""

import argparse
import asyncio
import json
import os
from pathlib import Path

import httpx

from agent_memory.evals.judge_demo import cross_provider_demo
from agent_memory.evals.judge_http import ProviderJudgeRouter
from agent_memory.evals.judge_pool import evaluate_table, judge_budget
from agent_memory.evals.table_pool import load_table_pool


async def main():
    p = argparse.ArgumentParser()
    p.add_argument("--pool", type=Path)
    p.add_argument("--rows", type=Path)
    p.add_argument("--table-kind", choices=("public-chinese", "synthetic-timeline"))
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--table-id", required=True)
    p.add_argument(
        "--demo-cross-provider",
        action="store_true",
        help="synthetic HTTP mock only; no real model calls or quota freeze",
    )
    a = p.parse_args()
    if a.demo_cross_provider:
        if a.pool or a.rows:
            p.error("demo uses only built-in synthetic rows, no supplied data/pool")
        print(json.dumps(await cross_provider_demo(a.output, a.table_id)))
        return
    if not a.pool or not a.rows:
        p.error("formal run requires --pool and --rows")
    config = json.loads(a.pool.read_text())
    if not a.table_kind:
        p.error("formal run requires --table-kind")
    policy = json.loads(Path("docs/evals/phase1-round3-policy-v3.json").read_text())
    try:
        judges = load_table_pool(config, policy, a.table_kind)
    except (ValueError, KeyError, OSError) as exc:
        p.error(str(exc))
    roles = policy["tables"][a.table_kind]
    excluded = {roles["answer_vendor"], *roles["annotation_vendors"]}
    with a.rows.open() as stream:
        rows = [json.loads(line) for line in stream if line.strip()]
    budget = judge_budget(len(rows), 1, 1)
    print(json.dumps({"workload_estimate": budget}), flush=True)
    tokens = {
        "TokenHub": os.environ.get("TOKENHUB_API_KEY") or os.environ.get("TENCENT_API_KEY", ""),
        "Ark": os.environ.get("ARK_API_KEY", ""),
    }
    if any(not tokens[j.provider] for j in judges):
        p.error("missing frozen provider credential; use with-llm, never token arguments")
    async with httpx.AsyncClient(timeout=60, trust_env=False) as client:
        transport = ProviderJudgeRouter(
            client,
            Path("docs/evals/prompts/judge-v1.txt").read_text(),
            tokens,
            os.environ.get("TENCENT_BASE_URL", "https://tokenhub.tencentmaas.com/v1"),
        )
        result = await evaluate_table(
            a.table_id, rows, judges, transport, a.output, excluded_vendors=excluded
        )
        print(
            json.dumps(
                {
                    "complete": result["complete"],
                    "judge": result["judge"],
                    "rows": len(result["records"]),
                }
            )
        )


if __name__ == "__main__":
    asyncio.run(main())
