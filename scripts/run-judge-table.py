"""Execute a frozen quota-ranked pool. Stage1 uses only explicit synthetic preflight rows."""

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path

import httpx

from agent_memory.evals.judge_http import TokenHubJudge
from agent_memory.evals.judge_pool import Judge, evaluate_table, rank_judges


async def main():
    p = argparse.ArgumentParser()
    p.add_argument("--pool", type=Path, required=True)
    p.add_argument("--rows", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--table-id", required=True)
    a = p.parse_args()
    config = json.loads(a.pool.read_text())
    if not config.get("quota_observed_at") or not config.get("quota_evidence_sha256"):
        p.error("actual quota query date/evidence required; no unverified pool")
    evidence = Path(config.get("quota_evidence_path", ""))
    if (
        not evidence.is_file()
        or hashlib.sha256(evidence.read_bytes()).hexdigest() != config["quota_evidence_sha256"]
    ):
        p.error("quota evidence file missing or changed")
    judges = rank_judges(
        [Judge(**r) for r in config["candidates"]], {"ByteDance", "DeepSeek", "Xiaomi"}
    )
    rows = [json.loads(line) for line in a.rows.read_text().splitlines()]
    if (judges[0].remaining_tokens or 0) < config["full_evaluation_judge_tokens_estimate"]:
        p.error("primary remaining quota does not cover estimated full evaluation")
    token = os.environ.get("TOKENHUB_API_KEY") or os.environ.get("TENCENT_API_KEY")
    if not token:
        p.error("use with-tencent; never pass token in arguments")
    async with httpx.AsyncClient(timeout=60, trust_env=False) as client:
        transport = TokenHubJudge(
            client,
            token,
            os.environ.get("TENCENT_BASE_URL", "https://tokenhub.tencentmaas.com/v1"),
            Path("docs/evals/prompts/judge-v1.txt").read_text(),
        )
        result = await evaluate_table(a.table_id, rows, judges, transport, a.output)
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
