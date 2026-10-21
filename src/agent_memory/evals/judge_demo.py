"""Explicit synthetic HTTP mock; exercises the production cross-cloud dispatcher."""

import json
from pathlib import Path
from typing import Any

import httpx

from agent_memory.evals.judge_http import ProviderJudgeRouter
from agent_memory.evals.judge_pool import Judge, evaluate_table


async def cross_provider_demo(output: Path, table_id: str) -> dict[str, Any]:
    calls: list[dict[str, Any]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        provider = "Ark" if request.url.host == "ark.cn-beijing.volces.com" else "TokenHub"
        expected = "Bearer mock-ark" if provider == "Ark" else "Bearer mock-tokenhub"
        if request.headers.get("Authorization") != expected:
            raise AssertionError("provider credential isolation failed")
        content = json.loads(body["messages"][1]["content"])
        calls.append({"provider": provider, "model": body["model"], "row_id": content["question"]})
        if provider == "TokenHub" and content["question"] == "synthetic-2":
            return httpx.Response(402, json={"error": {"code": "INJECTED_QUOTA_EXHAUSTED"}})
        return httpx.Response(
            200,
            json={
                "model": body["model"],
                "choices": [{"message": {"content": '{"correct":true,"reason_code":"MATCH"}'}}],
                "usage": {"total_tokens": 0, "completion_tokens_details": {"reasoning_tokens": 0}},
            },
        )

    rows = [
        {"row_id": f"synthetic-{i}", "question": f"synthetic-{i}", "reference": "4", "answer": "4"}
        for i in range(3)
    ]
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        router = ProviderJudgeRouter(
            client, "synthetic mock only", {"TokenHub": "mock-tokenhub", "Ark": "mock-ark"}
        )
        result = await evaluate_table(
            table_id,
            rows,
            [
                Judge("hy4-preview", "Tencent", True, None, "TokenHub"),
                Judge("glm-5-2-260617", "Zhipu", True, None, "Ark"),
            ],
            router,
            output,
            retry_delay=0,
        )
    summary = {
        "scope": "HTTP MockTransport synthetic fault injection; no live model requests or quota ranking",
        "http_requests": calls,
        "injected_http_status": 402,
        "live_model_calls": 0,
        "discarded_partial_rows": result["discarded_previous_partial_scores"],
        "final_rows": len(result["records"]),
        "final_provider": result["provider"],
        "final_judge": result["judge"],
        "single_provider_model_version": len(
            {(r["provider"], r["judge"], r["judge_version"]) for r in result["records"]}
        )
        == 1,
        "whole_table_regraded": [r["row_id"] for r in result["records"]]
        == [r["row_id"] for r in rows],
    }
    (output / "demo-summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary
