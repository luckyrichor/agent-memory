"""Whole-table judge failover; annotation roles and human decisions are never changed."""

import asyncio
import hashlib
import json
import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Judge:
    model: str
    vendor: str
    qualified: bool
    remaining_tokens: int | None


@dataclass(frozen=True)
class Grade:
    score: bool
    response_model: str
    reason_code: str
    usage: dict[str, int]


class JudgeFailure(RuntimeError):
    def __init__(self, status: int | None = None) -> None:
        super().__init__("judge request failed")
        self.status = status


def rank_judges(candidates: Sequence[Judge], excluded_vendors: set[str]) -> list[Judge]:
    eligible = [j for j in candidates if j.qualified and j.vendor not in excluded_vendors]
    if len({j.model for j in eligible}) < 3:
        raise ValueError("one primary and at least two qualified backups required")
    if any(j.remaining_tokens is None for j in eligible):
        raise ValueError("observed remaining quota required; unknown is not unlimited")
    return sorted(eligible, key=lambda j: (-(j.remaining_tokens or 0), j.model))


def judge_budget(questions: int, groups: int, repeats: int) -> dict[str, int]:
    if min(questions, groups, repeats) <= 0:
        raise ValueError("positive workload required")
    calls = questions * groups * repeats
    return {
        "questions": questions,
        "groups": groups,
        "repeats": repeats,
        "answer_calls": calls,
        "judge_calls": calls,
        "combined_calls": calls * 2,
        "judge_input_tokens_estimate": calls * 1000,
        "judge_output_tokens_estimate": calls * 100,
        "judge_total_tokens_estimate": calls * 1100,
    }


async def evaluate_table(
    table_id: str,
    rows: Sequence[dict[str, Any]],
    judges: Sequence[Judge],
    request: Callable[[Judge, dict[str, Any]], Awaitable[Grade]],
    output: Path,
    *,
    retry_delay: float = 1.0,
) -> dict[str, Any]:
    """Publish only a complete single-judge table. All failed attempts remain local."""
    if ".local" not in output.resolve().parts:
        raise ValueError("judge outputs must stay in private .local")
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,120}", table_id) or not rows or not judges:
        raise ValueError("valid table ID, rows and frozen judge pool required")
    if any(not j.qualified or j.vendor in {"ByteDance", "DeepSeek", "Xiaomi"} for j in judges):
        raise ValueError("judge pool violates frozen model-role independence")
    ids = [r.get("row_id") for r in rows]
    if any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != len(ids):
        raise ValueError("unique row IDs required")
    output.mkdir(parents=True, exist_ok=False)
    output.chmod(0o700)
    input_hash = hashlib.sha256(json.dumps(list(rows), sort_keys=True).encode()).hexdigest()
    attempts = []
    for index, judge in enumerate(judges):
        grades: list[dict[str, Any]] = []
        version: str | None = None
        failed = False
        attempt: dict[str, Any] = {"judge": judge.model, "rows_scored": 0, "complete": False}
        ledger = output / f"attempt-{index}.jsonl"
        for row in rows:  # restart from row zero after every switch
            grade = None
            for retry in range(3):
                try:
                    grade = await request(judge, row)
                    if not grade.response_model or (version and version != grade.response_model):
                        raise JudgeFailure()
                    break
                except JudgeFailure as error:
                    grade = None
                    with ledger.open("a") as stream:
                        stream.write(
                            json.dumps(
                                {
                                    "row_id": row["row_id"],
                                    "judge": judge.model,
                                    "retry": retry,
                                    "http_status": error.status,
                                    "valid": False,
                                }
                            )
                            + "\n"
                        )
                    if error.status in (400, 401, 402, 403, 404):
                        break
                    if retry < 2:
                        await asyncio.sleep(retry_delay * (2**retry))
            if grade is None:
                failed = True
                break
            version = grade.response_model
            record = {
                "row_id": row["row_id"],
                "judge": judge.model,
                "judge_version": version,
                "judge_version_source": "provider response.model; underlying weights not exposed",
                "graded_at": datetime.now(UTC).isoformat(),
                "score": grade.score,
                "reason_code": grade.reason_code,
                "usage": grade.usage,
            }
            grades.append(record)
            with ledger.open("a") as stream:
                stream.write(json.dumps(record) + "\n")
        attempt["rows_scored"] = len(grades)
        attempt["complete"] = not failed
        attempts.append(attempt)
        (output / "attempts.json").write_text(json.dumps(attempts, indent=2))
        if not failed:
            result = {
                "table_id": table_id,
                "input_sha256": input_hash,
                "judge": judge.model,
                "judge_version": version,
                "complete": True,
                "records": grades,
                "discarded_previous_partial_scores": sum(a["rows_scored"] for a in attempts[:-1]),
            }
            temporary = output / "result.pending"
            temporary.write_text(json.dumps(result, indent=2))
            temporary.replace(output / "result.json")
            return result
    raise JudgeFailure()  # no final comparison table exists
