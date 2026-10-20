"""Bounded provider regression probe. No raw responses or credentials on stdout."""

import asyncio
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import httpx

from agent_memory.evals.annotate import shared_sources, validate_batch
from agent_memory.evals.chinese_expansion import read_jsonl


async def main():
    root = Path(".local/phase1/chinese-expansion-v2")
    output = root / "minimax-disabled-probe"
    output.mkdir(exist_ok=False)
    output.chmod(0o700)
    token = os.environ.get("TOKENHUB_API_KEY") or os.environ["TENCENT_API_KEY"]
    base = os.environ.get("TENCENT_BASE_URL", "https://tokenhub.tencentmaas.com/v1").rstrip("/")
    prompt = Path("docs/evals/prompts/annotation-v4.txt").read_text()
    # Deterministic developer split only; not cherry-picked by model outcome.
    split = set(json.loads((root / "dulemon/split.json").read_text())["dev"])
    rows = [r for r in read_jsonl(root / "dulemon/items.jsonl") if r["conversation_id"] in split][
        :5
    ]
    body = {
        "model": "minimax-m2.7",
        "temperature": 0,
        "max_tokens": 8192,
        "response_format": {"type": "json_object"},
        "thinking": {"type": "disabled"},
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": json.dumps(shared_sources(rows), ensure_ascii=False)},
        ],
    }
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "model": body["model"],
        "temperature": 0,
        "thinking": body["thinking"],
        "request_sha256": hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest(),
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "probes": [],
        "official_guide": "https://intl.cloud.tencent.com/zh/document/product/1300/80636",
    }
    async with httpx.AsyncClient(timeout=120, trust_env=False) as client:
        for i in range(2):
            row = {"index": i, "http_status": None, "delivery": "unknown", "usage": None}
            try:
                response = await client.post(
                    base + "/chat/completions",
                    json=body,
                    headers={"Authorization": "Bearer " + token},
                )
                row["http_status"] = response.status_code
                row["delivery"] = "response_received"
                if response.is_success:
                    data = response.json()
                    (output / f"raw-{i}.json").write_text(
                        json.dumps({"request": body, "response": data}, ensure_ascii=False)
                    )
                    (output / f"raw-{i}.json").chmod(0o600)
                    row["usage"] = data.get("usage")
                    row["has_reasoning_content"] = bool(
                        data["choices"][0]["message"].get("reasoning_content")
                    )
                    row["reasoning_tokens"] = (
                        (data.get("usage") or {})
                        .get("completion_tokens_details", {})
                        .get("reasoning_tokens")
                    )
                    try:
                        validate_batch(data, {r["item_id"] for r in rows})
                        row["schema_valid"] = True
                    except (ValueError, KeyError, TypeError, IndexError) as exc:
                        row["schema_valid"] = False
                        row["validation_error_type"] = type(exc).__name__
            except httpx.HTTPError as exc:
                row["error_type"] = type(exc).__name__
            report["probes"].append(row)
            (output / "report.json").write_text(json.dumps(report, indent=2))
            print(json.dumps(row), flush=True)
    report["disabled_behavior_confirmed"] = all(
        r.get("http_status") == 200
        and r.get("schema_valid")
        and not r.get("has_reasoning_content")
        and r.get("reasoning_tokens") == 0
        for r in report["probes"]
    )
    (output / "report.json").write_text(json.dumps(report, indent=2))


asyncio.run(main())
