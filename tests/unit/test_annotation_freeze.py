import pytest

from agent_memory.evals.model_policy import require_frozen_annotation_model


@pytest.mark.parametrize("model", ["glm-5.2", "minimax-m2.7", "deepseek-v4.1-flash"])
def test_frozen_annotation_roles_do_not_follow_judge_rotation(model):
    with pytest.raises(ValueError, match="owner confirmation"):
        require_frozen_annotation_model(model, ("deepseek-v4-pro", "mimo-v2.6-flash"))


@pytest.mark.asyncio
async def test_ark_annotation_routes_to_ark_with_distinct_credential(monkeypatch, tmp_path):
    import json

    import httpx

    from agent_memory.evals import annotate as module

    original = httpx.AsyncClient
    calls = []

    def respond(request):
        calls.append(request)
        assert request.url.host == "ark.cn-beijing.volces.com"
        assert request.headers["Authorization"] == "Bearer mock-ark-not-real"
        body = json.loads(request.content)
        assert body["temperature"] == 0 and body["thinking"]["type"] == "disabled"
        return httpx.Response(
            200,
            json={
                "model": "deepseek-v4-pro-ga-260813",
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "labels": [
                                        {"item_id": "i", "label": "keep", "reason": "supported"}
                                    ]
                                }
                            )
                        }
                    }
                ],
                "usage": {"total_tokens": 1, "completion_tokens_details": {"reasoning_tokens": 0}},
            },
        )

    monkeypatch.setenv("ARK_API_KEY", "mock-ark-not-real")
    monkeypatch.setenv("TENCENT_API_KEY", "mock-tencent-not-real")
    monkeypatch.setattr(
        module.httpx,
        "AsyncClient",
        lambda **kw: original(**kw, transport=httpx.MockTransport(respond)),
    )
    items = tmp_path / "items.jsonl"
    items.write_text(
        json.dumps({"item_id": "i", "candidate": "synthetic preference", "source": []}) + "\n"
    )
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("synthetic prompt")
    out = tmp_path / ".local" / "out"
    await module.annotate(
        items,
        out,
        prompt,
        model="deepseek-v4-pro-ga-260813",
        batch_size=1,
        cache=tmp_path / ".local" / "cache",
        interval=0,
    )
    assert len(calls) == 1 and (out / "COMPLETE").exists()
    assert json.loads((out / "ledger.json").read_text())[0]["provider"] == "Ark"
