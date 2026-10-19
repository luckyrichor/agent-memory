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
from agent_memory.evals.model_preflight import MODELS


class LabelBatch(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    labels: list[Label]


def validate_batch(data: dict[str, Any], expected: set[str]) -> LabelBatch:
    parsed = LabelBatch.model_validate_json(data["choices"][0]["message"]["content"])
    if len(parsed.labels) != len(expected) or {x.item_id for x in parsed.labels} != expected:
        raise ValueError("annotation response ID coverage invalid")
    return parsed


def shared_sources(batch: list[dict[str, Any]]) -> dict[str, Any]:
    """Transmit identical sources once without shortening or merging distinct sources."""
    sources: dict[str, Any] = {}
    indices: dict[str, str] = {}
    items = []
    for row in batch:
        item = dict(row)
        source = item.pop("source")
        encoded = json.dumps(source, sort_keys=True, ensure_ascii=False)
        if encoded not in indices:
            indices[encoded] = str(len(indices))
            sources[indices[encoded]] = source
        item["source_ref"] = indices[encoded]
        items.append(item)
    return {"sources": sources, "items": items}


def partition_batches(lines: list[str], batch_size: int, shards: int) -> list[list[str]]:
    """Keep request boundaries identical to serial execution for cache replay."""
    if not 1 <= batch_size <= 50 or not 1 <= shards <= 4:
        raise ValueError("batch must be 1..50 and shards 1..4")
    parts: list[list[str]] = [[] for _ in range(shards)]
    for index, offset in enumerate(range(0, len(lines), batch_size)):
        parts[index % shards].extend(lines[offset : offset + batch_size])
    return parts


async def annotate_sharded(
    items: Path,
    output: Path,
    prompt: Path,
    *,
    model: str,
    batch_size: int,
    cache: Path,
    shards: int,
    retry_invalid_cache: bool,
    deduplicate_sources: bool,
) -> None:
    lines = [line for line in items.read_text().splitlines() if line.strip()]
    ids = [json.loads(line)["item_id"] for line in lines]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate annotation input ID")
    parts = partition_batches(lines, batch_size, shards)
    output.mkdir(parents=True, exist_ok=False)
    output.chmod(0o700)
    jobs = []
    directories = []
    for number, part in enumerate(parts):
        if not part:
            continue
        source = output / f"input-{number}.jsonl"
        source.write_text("\n".join(part) + "\n")
        source.chmod(0o600)
        destination = output / f"shard-{number}"
        directories.append(destination)
        jobs.append(
            annotate(
                source,
                destination,
                prompt,
                model=model,
                batch_size=batch_size,
                cache=cache,
                retry_invalid_cache=retry_invalid_cache,
                deduplicate_sources=deduplicate_sources,
            )
        )
    results = await asyncio.gather(*jobs, return_exceptions=True)
    (output / "manifest.json").write_text(
        json.dumps(
            {
                "model": model,
                "batch_size": batch_size,
                "shards": shards,
                "items_sha256": hashlib.sha256(items.read_bytes()).hexdigest(),
                "prompt_sha256": hashlib.sha256(prompt.read_bytes()).hexdigest(),
                "errors": [type(x).__name__ for x in results if isinstance(x, BaseException)],
                "note": "Same request batches as serial; scheduling order/concurrency differ.",
            },
            indent=2,
        )
    )
    if any(isinstance(x, BaseException) for x in results):
        raise RuntimeError("annotation shard incomplete; restricted child evidence retained")
    labels: list[Label] = []
    ledger: list[dict[str, Any]] = []
    for directory in directories:
        if not (directory / "COMPLETE").exists():
            raise RuntimeError("annotation shard completion missing")
        labels.extend(
            Label.model_validate_json(line)
            for line in (directory / "labels.jsonl").read_text().splitlines()
        )
        ledger.extend(json.loads((directory / "ledger.json").read_text()))
    indexed = {label.item_id: label for label in labels}
    if len(labels) != len(ids) or indexed.keys() != set(ids):
        raise ValueError("combined annotation ID coverage invalid")
    (output / "labels.jsonl").write_text(
        "".join(indexed[key].model_dump_json() + "\n" for key in ids)
    )
    (output / "ledger.json").write_text(json.dumps(ledger, indent=2))
    (output / "COMPLETE").write_text(hashlib.sha256(items.read_bytes()).hexdigest() + "\n")


async def annotate(
    items: Path,
    output: Path,
    prompt_path: Path,
    *,
    model: str,
    batch_size: int = 25,
    cache: Path,
    interval: float = 3,
    retry_invalid_cache: bool = False,
    deduplicate_sources: bool = False,
) -> None:
    if model not in MODELS:
        raise ValueError("model is not eligible under the frozen sampling policy")
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
                "messages": [
                    {"role": "system", "content": prompt},
                    {
                        "role": "user",
                        "content": json.dumps(
                            shared_sources(batch) if deduplicate_sources else batch,
                            ensure_ascii=False,
                        ),
                    },
                ],
            }
            body.update(
                {"reasoning_effort": "none"}
                if model == "hy3"
                else {"thinking": {"type": "disabled"}}
            )
            encoded = json.dumps(body, sort_keys=True, ensure_ascii=False).encode()
            key = hashlib.sha256(base.encode() + b"\x00" + encoded).hexdigest()
            cachefile = cache / (key + ".json")
            expected = {row["item_id"] for row in batch}
            invalid_cached: list[dict[str, Any]] = []
            if retry_invalid_cache:
                # Preserve every original reply. A retry has a separate immutable file;
                # replay validation never repairs labels or incurs another token charge.
                for retry in range(4):
                    cachefile = cache / (key + (f".retry-{retry}" if retry else "") + ".json")
                    if not cachefile.exists():
                        break
                    cached = json.loads(cachefile.read_text())
                    try:
                        validate_batch(cached["response"], expected)
                        break
                    except (ValidationError, ValueError, KeyError, TypeError, IndexError):
                        invalid_cached.append(
                            {
                                "file": cachefile.name,
                                "sha256": hashlib.sha256(cachefile.read_bytes()).hexdigest(),
                                "status": "invalid_cached_reply",
                                "new_usage": None,
                            }
                        )
                else:
                    raise RuntimeError("invalid cached reply retry limit reached")
            replayed = cachefile.exists()
            current: dict[str, Any] = {
                "model": model,
                "batch_hash": key,
                "item_count": len(batch),
                "replayed": replayed,
                "status": "started",
                "attempts": [],
                "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                "invalid_cached_replies": invalid_cached,
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
                current["usage"] = data.get("usage") if not replayed else None
                parsed = validate_batch(data, expected)
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
    parser.add_argument("--model", choices=MODELS, required=True)
    parser.add_argument("--batch-size", type=int, default=25)
    parser.add_argument("--retry-invalid-cache", action="store_true")
    parser.add_argument("--deduplicate-sources", action="store_true")
    parser.add_argument("--shards", type=int, default=1)
    args = parser.parse_args()
    for path in (args.output, args.cache):
        if ".local" not in path.resolve().parts:
            parser.error("raw annotation and cache must stay in ignored .local/")
    if args.shards != 1:
        asyncio.run(
            annotate_sharded(
                args.items,
                args.output,
                args.prompt,
                model=args.model,
                batch_size=args.batch_size,
                cache=args.cache,
                shards=args.shards,
                retry_invalid_cache=args.retry_invalid_cache,
                deduplicate_sources=args.deduplicate_sources,
            )
        )
        return
    asyncio.run(
        annotate(
            args.items,
            args.output,
            args.prompt,
            model=args.model,
            cache=args.cache,
            batch_size=args.batch_size,
            retry_invalid_cache=args.retry_invalid_cache,
            deduplicate_sources=args.deduplicate_sources,
        )
    )


if __name__ == "__main__":
    main()
