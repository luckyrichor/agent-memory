"""Independent model annotations with restricted local replay and metadata-only ledger."""

import argparse
import asyncio
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from agent_memory.evals.labeling import Label


class LabelBatch(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    labels: list[Label]


async def annotate(
    items: Path,
    output: Path,
    prompt_path: Path,
    *,
    model: str,
    batch_size: int = 25,
    cache: Path,
    interval: float = 3,
) -> None:
    if batch_size < 1 or batch_size > 50:
        raise ValueError("annotation batch must be 1..50")
    rows = [json.loads(line) for line in items.read_text().splitlines() if line.strip()]
    if len({r["item_id"] for r in rows}) != len(rows):
        raise ValueError("duplicate annotation input ID")
    output.mkdir(parents=True, exist_ok=False)
    output.chmod(0o700)
    cache.mkdir(parents=True, exist_ok=True)
    cache.chmod(0o700)
    prompt = prompt_path.read_text()
    token = os.environ.get("TOKENHUB_API_KEY") or os.environ.get("TENCENT_API_KEY")
    if not token:
        raise ValueError("use authorized shared configuration through with-tencent")
    base = os.environ.get("TENCENT_BASE_URL", "https://tokenhub.tencentmaas.com/v1").rstrip("/")
    ledger: list[dict[str, Any]] = []
    labels: list[Label] = []
    async with httpx.AsyncClient(timeout=120, trust_env=False) as client:
        for offset in range(0, len(rows), batch_size):
            batch = rows[offset : offset + batch_size]
            body: dict[str, Any] = {
                "model": model,
                "temperature": 0,
                "max_tokens": 8192,
                "response_format": {"type": "json_object"},
                "thinking": {"type": "disabled"},
                "messages": [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": json.dumps(batch, ensure_ascii=False)},
                ],
            }
            encoded = json.dumps(body, sort_keys=True, ensure_ascii=False).encode()
            key = hashlib.sha256(base.encode() + b"\x00" + encoded).hexdigest()
            cachefile = cache / (key + ".json")
            replayed = cachefile.exists()
            current: dict[str, Any] = {
                "model": model,
                "batch_hash": key,
                "item_count": len(batch),
                "replayed": replayed,
                "status": "started",
                "attempts": [],
                "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
            }
            ledger.append(current)
            (output / "ledger.json").write_text(json.dumps(ledger, indent=2))
            attempts: list[dict[str, Any]] = []
            data: dict[str, Any] = {}
            try:
                if replayed:
                    data = json.loads(cachefile.read_text())["response"]
                else:
                    for attempt in range(5):
                        await asyncio.sleep(interval if attempt == 0 else min(60, 5 * 2**attempt))
                        try:
                            response = await client.post(
                                base + "/chat/completions",
                                json=body,
                                headers={"Authorization": "Bearer " + token},
                            )
                        except httpx.HTTPError as exc:
                            attempts.append(
                                {"error_type": type(exc).__name__, "delivery": "unknown"}
                            )
                            current["attempts"] = attempts
                            (output / "ledger.json").write_text(json.dumps(ledger, indent=2))
                            continue
                        attempts.append(
                            {
                                "http_status": response.status_code,
                                "outbound_texts": len(body["messages"]),
                                "outbound_text_bytes": sum(
                                    len(m["content"].encode()) for m in body["messages"]
                                ),
                            }
                        )
                        current["attempts"] = attempts
                        (output / "ledger.json").write_text(json.dumps(ledger, indent=2))
                        if response.status_code in (429, 500, 502, 503, 504):
                            continue
                        if not response.is_success:
                            raise RuntimeError(
                                "annotation HTTP failure: " + str(response.status_code)
                            )
                        data = response.json()
                        break
                    if not data:
                        raise RuntimeError("annotation retry limit reached; keep partial ledger")
                if not replayed:
                    cachefile.write_text(
                        json.dumps({"request": body, "response": data}, ensure_ascii=False)
                    )
                    cachefile.chmod(0o600)
                parsed = LabelBatch.model_validate_json(data["choices"][0]["message"]["content"])
                expected = {row["item_id"] for row in batch}
                if (
                    len(parsed.labels) != len(expected)
                    or {x.item_id for x in parsed.labels} != expected
                ):
                    raise ValueError("annotation response ID coverage invalid")
                labels.extend(parsed.labels)
            except Exception as exc:
                current.update(status="failed", error_type=type(exc).__name__, attempts=attempts)
                (output / "ledger.json").write_text(json.dumps(ledger, indent=2))
                if isinstance(exc, ValidationError):
                    raise TypeError(
                        "annotation format invalid; restricted raw artifact retained"
                    ) from None
                raise
            current.update(
                {
                    "model": model,
                    "response_model": data.get("model"),
                    "batch_hash": key,
                    "item_count": len(batch),
                    "replayed": replayed,
                    "attempts": attempts,
                    "usage": data.get("usage") if not replayed else None,
                    "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                    "created_at": datetime.now(UTC).isoformat(),
                    "status": "validated",
                }
            )
            (output / "ledger.json").write_text(json.dumps(ledger, indent=2))
            (output / "labels.jsonl").write_text(
                "".join(x.model_dump_json() + "\n" for x in labels)
            )
            print(
                json.dumps(
                    {
                        "model": model,
                        "completed": len(labels),
                        "total": len(rows),
                        "replayed": replayed,
                    }
                ),
                flush=True,
            )
    (output / "COMPLETE").write_text(hashlib.sha256(items.read_bytes()).hexdigest() + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--items", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--prompt", type=Path, default=Path("docs/evals/prompts/annotation-v1.txt"))
    parser.add_argument("--model", choices=("deepseek-v4.1-flash", "minimax-m3"), required=True)
    args = parser.parse_args()
    for path in (args.output, args.cache):
        if ".local" not in path.resolve().parts:
            parser.error("raw annotation and cache must stay in ignored .local/")
    asyncio.run(annotate(args.items, args.output, args.prompt, model=args.model, cache=args.cache))


if __name__ == "__main__":
    main()
