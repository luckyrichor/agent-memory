import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

from agent_memory.evals.annotate import shared_sources
from agent_memory.evals.evidence_v3 import DIMENSIONS
from agent_memory.evals.temporal_preflight import virtual_item


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "client_path",
    [
        "scripts/temporal-annotation-client-v2.py",
        "scripts/temporal-annotation-client-v3.py",
        "scripts/temporal-annotation-client-v4.py",
    ],
)
async def test_side_refreshes_completed_response_cache_before_batch_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, client_path: str
) -> None:
    spec = importlib.util.spec_from_file_location("temporal_replay_regression", client_path)
    assert spec and spec.loader
    client = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(client)
    client.BASE = tmp_path / "private"
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("Entirely fictional transport test.")
    model = "hy-role"

    def completed_response(number: int) -> dict[str, Any]:
        item = virtual_item(number)
        wire = {**item, "item_id": "i0"}
        body = {
            "model": model,
            "temperature": 0,
            "thinking": {"type": "disabled"},
            "max_tokens": 8192,
            "messages": [
                {"role": "system", "content": prompt.read_text()},
                {
                    "role": "user",
                    "content": json.dumps(shared_sources([wire]), ensure_ascii=False),
                },
            ],
        }
        label = {
            "item_id": "i0",
            "label": "discard",
            "reason": "missing",
            "temporal": "临时" if number % 2 else "长期",
            "evidence": {dimension: [] for dimension in DIMENSIONS},
        }
        directory = client.BASE / f"batch-{number}"
        directory.mkdir(parents=True)
        (directory / "0000-request.json").write_text(json.dumps(body))
        (directory / "0000-response-0.json").write_text(
            json.dumps(
                {
                    "model": model,
                    "choices": [
                        {
                            "message": {"content": json.dumps({"labels": [label]})},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"total_tokens": 10},
                }
            )
        )
        (directory / "0000-checked.jsonl").write_text("{}\n")
        return item

    completed_response(0)
    client.index_cache()
    assert len(client.INDEX) == 1
    later_item = completed_response(1)

    async def forbidden_post(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("A completed unchanged side must not incur another API call")

    monkeypatch.setattr(client, "post", forbidden_post)
    monkeypatch.setenv("TENCENT_BASE_URL", "https://example.invalid")
    monkeypatch.setenv("TENCENT_API_KEY", "fictional-test-value")
    output = tmp_path / "replacement"
    assert await client.side(output, model, [later_item], prompt, "annotation")
    ledger = json.loads((output / model / "ledger.json").read_text())
    assert ledger[0]["cache_hit"] is True
    assert ledger[0]["attempts"] == []
    assert "usage" not in ledger[0]
    assert ledger[0]["cached_original_usage"]["total_tokens"] == 10


@pytest.mark.asyncio
async def test_turbo_uses_one_candidate_packets_without_repairing_model_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = importlib.util.spec_from_file_location(
        "temporal_single_packet_regression", "scripts/temporal-annotation-client-v3.py"
    )
    assert spec and spec.loader
    client = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(client)
    client.BASE = tmp_path / "private"
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("Entirely fictional packet format regression.")
    packets = []

    async def fake_post(
        http_client: Any, body: Any, token: Any, base: Any, entry: Any, directory: Any, offset: Any
    ) -> dict[str, Any]:
        payload = json.loads(body["messages"][-1]["content"])
        packets.append(payload)
        assert len(payload["items"]) == 1
        entry.update(http=200, attempts=[{"http": 200}])
        label = {
            "item_id": payload["items"][0]["item_id"],
            "label": "discard",
            "reason": "missing",
            "temporal": "长期",
            "evidence": {dimension: [] for dimension in DIMENSIONS},
        }
        return {
            "model": body["model"],
            "choices": [
                {"message": {"content": json.dumps({"labels": [label]})}, "finish_reason": "stop"}
            ],
            "usage": {"total_tokens": 10},
        }

    monkeypatch.setattr(client, "post", fake_post)
    monkeypatch.setenv("TENCENT_BASE_URL", "https://example.invalid")
    monkeypatch.setenv("TENCENT_API_KEY", "fictional-test-value")
    rows = [virtual_item(0), virtual_item(1)]
    model = "hunyuan-turbos-vision-video-20250728"
    output = tmp_path / "single-packet"
    assert await client.side(output, model, rows, prompt, "annotation")
    assert len(packets) == 2
    checked = [
        json.loads(line) for line in (output / model / "checked.jsonl").read_text().splitlines()
    ]
    assert {row["item_id"] for row in checked} == {row["item_id"] for row in rows}
    assert all(row["schema_valid"] and row["citation_valid"] for row in checked)


@pytest.mark.asyncio
async def test_new_account_batch_does_not_replay_retired_batch4(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = importlib.util.spec_from_file_location(
        "new_account_cache", "scripts/temporal-annotation-client-v4.py"
    )
    assert spec and spec.loader
    client = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(client)
    assert client.BASE == Path(".local/phase1/round3/new-accounts-v1/increment-batches-v6")
    historical = tmp_path / "old-account" / "batch-004"
    historical.mkdir(parents=True)
    client.BASE = tmp_path / "new-account"
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("Fictional test")
    row = virtual_item(0)
    body = {
        "model": "hy-role",
        "temperature": 0,
        "thinking": {"type": "disabled"},
        "max_tokens": 8192,
        "messages": [
            {"role": "system", "content": prompt.read_text()},
            {
                "role": "user",
                "content": json.dumps(
                    shared_sources([{**row, "item_id": "i0"}]), ensure_ascii=False
                ),
            },
        ],
    }
    data = {
        "model": "hy-role",
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "content": json.dumps(
                        {
                            "labels": [
                                {
                                    "item_id": "i0",
                                    "label": "discard",
                                    "temporal": "长期",
                                    "reason": "missing",
                                    "evidence": {dimension: [] for dimension in DIMENSIONS},
                                }
                            ]
                        }
                    )
                },
            }
        ],
        "usage": {"total_tokens": 10},
    }
    (historical / "0000-request.json").write_text(json.dumps(body))
    (historical / "0000-response-0.json").write_text(json.dumps(data))
    (historical / "0000-checked.jsonl").write_text("{}\n")
    calls = []
    monkeypatch.setattr(client, "STRUCTURED_MODELS", {"hy-role"})

    async def fresh_post(*args: Any) -> dict[str, Any]:
        calls.append(args[1])
        assert args[1]["response_format"]["json_schema"]["strict"] is True
        assert (
            args[1]["response_format"]["json_schema"]["schema"]
            == client.TemporalEvidenceBatch.model_json_schema()
        )
        assert args[1]["messages"] == body["messages"]
        args[4].update(http=200, attempts=[{"http": 200}])
        return data

    monkeypatch.setattr(client, "post", fresh_post)
    monkeypatch.setenv("TENCENT_BASE_URL", "https://example.invalid")
    monkeypatch.setenv("TENCENT_API_KEY", "fictional-test-value")
    output = client.BASE / "batch-004"
    assert await client.side(output, "hy-role", [row], prompt, "annotation")
    assert len(calls) == 1
    ledger = json.loads((output / "hy-role" / "ledger.json").read_text())
    assert ledger[0]["cache_hit"] is False
    assert ledger[0]["account"] == "tokenhub-secondary"
    assert ledger[0]["usage"]["total_tokens"] == 10
