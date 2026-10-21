import json

import httpx
import pytest

from agent_memory.evals.judge_http import TokenHubJudge
from agent_memory.evals.judge_pool import Judge, JudgeFailure


@pytest.mark.asyncio
async def test_transport_omits_experiment_identity_and_enforces_frozen_controls():
    def respond(request):
        body = json.loads(request.content)
        assert body["temperature"] == 0 and body["thinking"] == {"type": "disabled"}
        assert "system_group" not in body["messages"][1]["content"]
        return httpx.Response(
            200,
            json={
                "model": "version-test",
                "choices": [{"message": {"content": '{"correct":true,"reason_code":"MATCH"}'}}],
                "usage": {"total_tokens": 10},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        adapter = TokenHubJudge(client, "test-token-not-real", "https://fixture", "fixture-prompt")
        grade = await adapter(
            Judge("judge", "Tencent", True, 100),
            {"question": "fixture", "reference": "yes", "answer": "yes", "system_group": "system"},
        )
    assert grade.score and grade.response_model == "version-test"


@pytest.mark.asyncio
async def test_reasoning_and_non_boolean_grade_are_rejected():
    for content, reasoning in [
        ('{"correct":"true","reason_code":"MATCH"}', None),
        ('{"correct":true,"reason_code":"MATCH"}', "thinking despite disabled"),
    ]:

        def respond(request, content=content, reasoning=reasoning):
            return httpx.Response(
                200,
                json={
                    "model": "fixture",
                    "choices": [{"message": {"content": content, "reasoning_content": reasoning}}],
                },
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            adapter = TokenHubJudge(
                client, "test-token-not-real", "https://fixture", "fixture-prompt"
            )
            with pytest.raises(JudgeFailure):
                await adapter(
                    Judge("judge", "Tencent", True, 100),
                    {"question": "q", "reference": "r", "answer": "a"},
                )


@pytest.mark.asyncio
async def test_production_router_cross_cloud_full_table_demo(tmp_path):
    from agent_memory.evals.judge_demo import cross_provider_demo

    root = tmp_path / ".local" / "cross-cloud"
    report = await cross_provider_demo(root, "cross_cloud")
    assert report["live_model_calls"] == 0
    assert report["discarded_partial_rows"] == 2
    assert report["whole_table_regraded"] and report["single_provider_model_version"]
    assert report["final_provider"] == "Ark" and report["final_rows"] == 3
    assert [r["provider"] for r in report["http_requests"]] == ["TokenHub"] * 3 + ["Ark"] * 3
    assert [r["row_id"] for r in report["http_requests"][-3:]] == [
        f"synthetic-{i}" for i in range(3)
    ]
