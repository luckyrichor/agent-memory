import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

from agent_memory.evals.annotate import shared_sources
from agent_memory.evals.evidence_v3 import DIMENSIONS
from agent_memory.evals.temporal_preflight import virtual_item


@pytest.mark.asyncio
async def test_side_refreshes_completed_response_cache_before_batch_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = importlib.util.spec_from_file_location(
        "temporal_replay_regression", "scripts/temporal-annotation-client-v2.py"
    )
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
