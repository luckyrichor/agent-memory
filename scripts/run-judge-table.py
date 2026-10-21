"""Execute a frozen quota-ranked pool. Stage1 uses only explicit synthetic preflight rows."""

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path

import httpx

from agent_memory.evals.judge_demo import cross_provider_demo
from agent_memory.evals.judge_http import ProviderJudgeRouter
from agent_memory.evals.judge_pool import Judge, evaluate_table, rank_judges


async def main():
    p = argparse.ArgumentParser()
    p.add_argument("--pool", type=Path)
    p.add_argument("--rows", type=Path)
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
    if not config.get("quota_observed_at") or not config.get("quota_evidence_sha256"):
        p.error("actual quota query date/evidence required; no unverified pool")
    evidence = Path(config.get("quota_evidence_path", ""))
    if (
        not evidence.is_file()
        or hashlib.sha256(evidence.read_bytes()).hexdigest() != config["quota_evidence_sha256"]
    ):
        p.error("quota evidence file missing or changed")
    policy = json.loads(Path("docs/evals/phase1-round3-policy-v1.json").read_text())
    excluded = set(policy["judge_excluded_vendors"])
    judges = rank_judges([Judge(**r) for r in config["candidates"]], excluded)
    with a.rows.open() as stream:
        rows = [json.loads(line) for line in stream if line.strip()]
    if (judges[0].remaining_tokens or 0) < config["full_evaluation_judge_tokens_estimate"]:
        p.error("primary remaining quota does not cover estimated full evaluation")
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
