"""Real provider preflight; public/synthetic probes only, never real user memory.

Raw replies and prompts are restricted local artifacts. The exported report has no text.
No caching in preflight: repeated probes MUST actually call the provider.
"""

import argparse
import asyncio
import hashlib
import json
import os
import platform
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict

from agent_memory.evals.metrics import latency
from agent_memory.evals.model_policy import require_disabled_thinking

MODELS = (
    "deepseek-v4.1-flash",
    "minimax-m3",
    "glm-5.2",
    "hy3",
    "minimax-m2.7",
    "deepseek-v4-pro-0813",
    "deepseek-v4-pro-202606",
)
EXPERIMENTAL_MODELS = ("kimi-k3",)
ARK_MODELS = ("doubao-seed-2-1-pro-260915",)


class ProbeReply(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    label: str
    reason: str


async def probe(
    client: httpx.AsyncClient, model: str, prompt: str, number: int, *, repeated: bool
) -> tuple[dict[str, Any], dict[str, Any]]:
    candidate = "事实样本0" if repeated else f"事实样本{number}"
    expected = "same" if repeated or number % 2 == 0 else "different"
    reference = candidate if expected == "same" else "另一个事实"
    text = json.dumps({"candidate": candidate, "reference": reference}, ensure_ascii=False)
    body: dict[str, Any] = {
        "model": model,
        "temperature": 0,
        "max_tokens": 256,
        "response_format": {"type": "json_object"},
        "messages": [{"role": "system", "content": prompt}, {"role": "user", "content": text}],
    }
    body.update(
        {"reasoning_effort": "none"} if model == "hy3" else {"thinking": {"type": "disabled"}}
    )
    ark = model in ARK_MODELS
    base = (
        "https://ark.cn-beijing.volces.com/api/v3"
        if ark
        else os.environ.get("TENCENT_BASE_URL", "https://tokenhub.tencentmaas.com/v1").rstrip("/")
    )
    token = (
        os.environ.get("ARK_API_KEY")
        if ark
        else (os.environ.get("TOKENHUB_API_KEY") or os.environ.get("TENCENT_API_KEY"))
    )
    if not token:
        raise ValueError("shared provider credential missing; use with-ark or with-tencent")
    started = time.monotonic()
    record: dict[str, Any] = {
        "model": model,
        "provider": "Ark" if ark else "TokenHub",
        "base_url": base,
        "number": number,
        "repeated": repeated,
        "expected": expected,
        "request_bytes": len(text.encode()) + len(prompt.encode()),
        "outbound_texts": 2,
    }
    raw: dict[str, Any] = {"request": body}
    try:
        response = await client.post(
            base + "/chat/completions", json=body, headers={"Authorization": f"Bearer {token}"}
        )
        record["http_status"] = response.status_code
        # Do not serialize request headers, exceptions, or provider error messages.
        if response.is_success:
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            raw["response"] = data
            record["usage"] = data.get("usage")
            record["response_model"] = data.get("model")
            try:
                require_disabled_thinking(data)
                record["observed_disabled_thinking"] = True
            except RuntimeError:
                record["observed_disabled_thinking"] = False
            parsed = ProbeReply.model_validate_json(content)
            record["format_valid"] = parsed.label in ("same", "different")
            record["label"] = parsed.label
            record["correct"] = parsed.label == expected
        else:
            record["format_valid"] = False
    except (httpx.HTTPError, ValueError, KeyError, TypeError, IndexError) as exc:
        record["error_type"] = type(exc).__name__
        record["format_valid"] = False
    record["latency_ms"] = (time.monotonic() - started) * 1000
    return record, raw


async def run(
    output: Path,
    prompt_path: Path,
    *,
    format_samples: int = 100,
    models: tuple[str, ...] = MODELS,
    interval: float = 2.5,
) -> None:
    if format_samples != 100:
        raise ValueError("plan requires exactly 100 format samples per model")
    output.mkdir(parents=True, exist_ok=False)
    output.chmod(0o700)
    prompt = prompt_path.read_text()
    records = []
    raw_records = []
    async with httpx.AsyncClient(timeout=60, trust_env=False) as client:
        for model in models:
            # One minimal role probe, five identical probes, then 100 distinct probes.
            for number in range(106):
                await asyncio.sleep(interval)
                attempts = []
                for attempt in range(5):
                    record, raw = await probe(client, model, prompt, number, repeated=number < 6)
                    attempts.append({k: v for k, v in record.items() if k != "label"})
                    if record.get("http_status") != 429:
                        break
                    await asyncio.sleep(min(60, 5 * 2**attempt))
                record["attempts"] = attempts
                records.append(record)
                raw_records.append(raw)
                (output / "progress.json").write_text(json.dumps(records, indent=2))
                raw_progress = output / "raw-local-only.json"
                raw_progress.write_text(json.dumps(raw_records, ensure_ascii=False))
                raw_progress.chmod(0o600)
                if number % 25 == 0:
                    print(
                        json.dumps({"progress_model": model, "completed": number + 1}), flush=True
                    )
                if (
                    record.get("http_status") in (400, 401, 402, 403, 404)
                    or record.get("observed_disabled_thinking") is False
                ):
                    # Repeating quota/auth failures cannot qualify a model. Retain
                    # the failed probe and continue with the next eligible model.
                    break
            model_rows = [r for r in records if r["model"] == model]
            repeated = model_rows[1:6]
            formatted = model_rows[6:]
            valid = sum(bool(r.get("format_valid")) for r in formatted)
            consistent = (
                len(repeated) == 5
                and all(r.get("format_valid") for r in repeated)
                and len({r.get("label") for r in repeated}) == 1
            )
            summary = {
                "model": model,
                "calls": len(model_rows),
                "format_valid": valid,
                "format_n": len(formatted),
                "consistent_5": consistent,
                "preflight_pass": len(formatted) == 100
                and valid >= 99
                and consistent
                and bool(model_rows[0].get("format_valid"))
                and model not in EXPERIMENTAL_MODELS
                and all(r.get("observed_disabled_thinking") for r in model_rows),
                "observed_disabled_thinking": all(
                    r.get("observed_disabled_thinking") for r in model_rows
                ),
                "sampling_control_eligible": model not in EXPERIMENTAL_MODELS,
                "latency_ms": latency([r["latency_ms"] for r in model_rows]),
                "http_429": sum(
                    a.get("http_status") == 429 for r in model_rows for a in r["attempts"]
                ),
            }
            print(json.dumps(summary), flush=True)
            (output / f"{model}-summary.json").write_text(json.dumps(summary, indent=2))
    report = {
        "created_at": datetime.now(UTC).isoformat(),
        "python": platform.python_version(),
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "parameters": {
            "temperature": 0,
            "max_tokens": 256,
            "response_format": {"type": "json_object"},
            "concurrency": 1,
            "interval_seconds": interval,
        },
        "scope": "synthetic exact-match format probes; NOT judge calibration",
        "records": records,
    }
    (output / "report.json").write_text(json.dumps(report, indent=2))
    raw_path = output / "raw-local-only.json"
    raw_path.write_text(json.dumps(raw_records, ensure_ascii=False))
    raw_path.chmod(0o600)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--prompt", type=Path, default=Path("docs/evals/prompts/preflight-v1.txt"))
    parser.add_argument(
        "--models",
        nargs="+",
        choices=MODELS + ARK_MODELS + EXPERIMENTAL_MODELS,
        default=list(MODELS),
    )
    parser.add_argument("--interval", type=float, default=2.5)
    args = parser.parse_args()
    if ".local" not in args.output.resolve().parts:
        parser.error("raw preflight artifacts must be under ignored .local/")
    asyncio.run(run(args.output, args.prompt, models=tuple(args.models), interval=args.interval))


if __name__ == "__main__":
    main()
