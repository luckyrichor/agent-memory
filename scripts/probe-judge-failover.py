import asyncio
import json
import os
from pathlib import Path

import httpx

from agent_memory.evals.judge_http import TokenHubJudge
from agent_memory.evals.judge_pool import Judge, JudgeFailure, evaluate_table


async def main():
    for model, folder in [
        ("hy4-preview", "preflight-hy4-preview"),
        ("glm-5v-turbo", "preflight-glm-5v-turbo-retest"),
    ]:
        assert json.loads(
            (Path(".local/phase1/round3") / folder / (model + "-summary.json")).read_text()
        )["preflight_pass"]
    root = Path(".local/phase1/round3/failover-live-synthetic")
    calls = []
    async with httpx.AsyncClient(timeout=60, trust_env=False) as client:
        real = TokenHubJudge(
            client,
            os.environ.get("TOKENHUB_API_KEY") or os.environ["TENCENT_API_KEY"],
            os.environ["TENCENT_BASE_URL"],
            Path("docs/evals/prompts/judge-v1.txt").read_text(),
        )

        async def controlled(judge, row):
            calls.append({"judge": judge.model, "row_id": row["row_id"]})
            if judge.model == "hy4-preview" and row["row_id"] == "synthetic-2":
                raise JudgeFailure(402)
            return await real(judge, row)

        rows = [
            {
                "row_id": "synthetic-" + str(i),
                "question": "2加2是多少？",
                "reference": "4",
                "answer": "4",
            }
            for i in range(3)
        ]
        result = await evaluate_table(
            "phase1_synthetic_fault_injection",
            rows,
            [
                Judge("hy4-preview", "Tencent", True, None),
                Judge("glm-5v-turbo", "Zhipu", True, None),
            ],
            controlled,
            root,
            retry_delay=0.1,
        )
    assert result["judge"] == "glm-5v-turbo" and result["discarded_previous_partial_scores"] == 2
    assert {r["judge"] for r in result["records"]} == {"glm-5v-turbo"} and len(
        result["records"]
    ) == 3
    evidence = {
        "scope": "stage1 synthetic integration only; injected HTTP402 after two actual grades, not actual provider quota exhaustion, not a quota-ranked formal pool",
        "request_sequence": calls,
        "complete_single_judge": True,
        "discarded_partial_rows": 2,
        "final_rows": 3,
        "real_provider_grade_calls": 5,
        "final_judge": result["judge"],
        "version": result["judge_version"],
    }
    (root / "summary.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps(evidence))


asyncio.run(main())
