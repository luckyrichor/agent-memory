import json

import httpx
import pytest

from agent_memory.evals import annotate as module
from agent_memory.evals.model_preflight import probe


async def test_preflight_does_not_turn_http_error_into_negative_judgment(monkeypatch):
    monkeypatch.setenv("TOKENHUB_API_KEY", "unit-test-only")
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(429, json={"error": {"message": "provider error"}})
        )
    ) as client:
        record, raw = await probe(client, "minimax-m3", "test prompt", 0, repeated=True)
    assert record["http_status"] == 429 and not record["format_valid"]
    assert "label" not in record and "provider error" not in json.dumps(record)
    assert "Authorization" not in json.dumps(raw)


async def test_annotation_replay_and_failure_ledger_do_not_expose_credentials(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("TOKENHUB_API_KEY", "unit-test-only")
    items, prompt = tmp_path / "items", tmp_path / "prompt"
    items.write_text(json.dumps({"item_id": "a", "candidate": "public synthetic text"}) + "\n")
    prompt.write_text("test versioned prompt")
    calls = []
    original = httpx.AsyncClient

    def respond(request):
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "model": "deepseek-v4.1-flash",
                "usage": {"total_tokens": 20},
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "labels": [
                                        {
                                            "item_id": "a",
                                            "label": "keep",
                                            "reason": "source supports it",
                                        }
                                    ]
                                }
                            )
                        }
                    }
                ],
            },
        )

    monkeypatch.setattr(
        module.httpx,
        "AsyncClient",
        lambda **kw: original(**kw, transport=httpx.MockTransport(respond)),
    )
    for name in ["first", "replay"]:
        await module.annotate(
            items,
            tmp_path / name,
            prompt,
            model="deepseek-v4.1-flash",
            cache=tmp_path / "cache",
            interval=0,
        )
    assert len(calls) == 1
    assert (tmp_path / "replay/COMPLETE").exists()
    ledger = json.loads((tmp_path / "replay/ledger.json").read_text())
    assert ledger[0]["replayed"] and ledger[0]["usage"] is None
    for name in ["first", "replay"]:
        text = (tmp_path / name / "ledger.json").read_text()
        assert "public synthetic text" not in text and "unit-test-only" not in text
    # Different prompt hash is a new call; an invalid ID is not accepted or marked complete.
    prompt.write_text("new prompt")
    items.write_text(json.dumps({"item_id": "other"}) + "\n")
    with pytest.raises(ValueError, match="ID coverage"):
        await module.annotate(
            items,
            tmp_path / "invalid",
            prompt,
            model="deepseek-v4.1-flash",
            cache=tmp_path / "cache",
            interval=0,
        )
    assert not (tmp_path / "invalid/COMPLETE").exists()
    failed = json.loads((tmp_path / "invalid/ledger.json").read_text())[0]
    assert failed["status"] == "failed" and failed["error_type"] == "ValueError"


async def test_invalid_model_json_is_retained_locally_but_not_in_exception(tmp_path, monkeypatch):
    monkeypatch.setenv("TOKENHUB_API_KEY", "unit-test-only")
    items, prompt = tmp_path / "items", tmp_path / "prompt"
    items.write_text('{"item_id":"a"}\n')
    prompt.write_text("test prompt")
    original = httpx.AsyncClient

    def respond(_):
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"labels": RAW_TEXT_MARKER_NOT_FOR_LOGS}'}}]
            },
        )

    monkeypatch.setattr(
        module.httpx,
        "AsyncClient",
        lambda **kw: original(**kw, transport=httpx.MockTransport(respond)),
    )
    with pytest.raises(TypeError, match="format invalid") as error:
        await module.annotate(
            items,
            tmp_path / "run",
            prompt,
            model="deepseek-v4.1-flash",
            cache=tmp_path / "cache",
            interval=0,
        )
    assert "RAW_TEXT_MARKER_NOT_FOR_LOGS" not in str(error.value)
    assert not (tmp_path / "run/COMPLETE").exists()
    assert (
        json.loads((tmp_path / "run/ledger.json").read_text())[0]["error_type"] == "ValidationError"
    )


async def test_explicit_invalid_cache_retry_preserves_original_and_replays_valid_reply(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("TOKENHUB_API_KEY", "unit-test-only")
    items, prompt, cache = tmp_path / "items", tmp_path / "prompt", tmp_path / "cache"
    items.write_text('{"item_id":"a"}\n')
    prompt.write_text("fixed prompt")
    original, calls = httpx.AsyncClient, []

    def respond(request):
        body = json.loads(request.content)
        assert body["reasoning_effort"] == "none" and "thinking" not in body
        calls.append(body)
        content = (
            "INVALID"
            if len(calls) == 1
            else json.dumps({"labels": [{"item_id": "a", "label": "keep", "reason": "supported"}]})
        )
        return httpx.Response(
            200, json={"usage": {"total_tokens": 7}, "choices": [{"message": {"content": content}}]}
        )

    monkeypatch.setattr(
        module.httpx,
        "AsyncClient",
        lambda **kw: original(**kw, transport=httpx.MockTransport(respond)),
    )
    with pytest.raises(TypeError, match="format invalid"):
        await module.annotate(
            items, tmp_path / "failed", prompt, model="hy3", cache=cache, interval=0
        )
    raw = next(cache.glob("*.json"))
    original_bytes = raw.read_bytes()
    for name in ("retry", "replay"):
        await module.annotate(
            items,
            tmp_path / name,
            prompt,
            model="hy3",
            cache=cache,
            interval=0,
            retry_invalid_cache=True,
        )
    assert len(calls) == 2 and raw.read_bytes() == original_bytes
    assert len(list(cache.glob("*.json"))) == 2
    retry = json.loads((tmp_path / "retry/ledger.json").read_text())[0]
    replay = json.loads((tmp_path / "replay/ledger.json").read_text())[0]
    assert retry["usage"]["total_tokens"] == 7 and not retry["replayed"]
    assert replay["usage"] is None and replay["replayed"]
    assert len(replay["invalid_cached_replies"]) == 1
