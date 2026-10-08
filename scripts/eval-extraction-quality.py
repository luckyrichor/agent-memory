"""Separate real extraction smoke evaluation on labeled synthetic cases.

Credential configuration is consumed locally, never printed or saved in results.
Term coverage is a reproducible heuristic, NOT a human quality grade.
"""

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx

from agent_memory.domain.enums import ScopeKind
from agent_memory.domain.errors import RetryableExtractionError
from agent_memory.domain.events import Event, EventDraft, EventType
from agent_memory.domain.models import MemoryScope
from agent_memory.infrastructure.llm_extractor import LLMExtractor

CASES = [
    (
        "deployment",
        "Deployment succeeded after checking the configuration file. "
        "Reusable lesson: check configuration before deployment.",
        ["config"],
        True,
    ),
    (
        "database",
        "Database connection timeout was resolved by setting the connection pool size. "
        "Reusable lesson: check connection pool limits when connections time out.",
        ["pool"],
        True,
    ),
    (
        "cache",
        "Stale results were resolved by invalidating the cache after updates. "
        "Reusable lesson: invalidate cache on update.",
        ["cache"],
        True,
    ),
    (
        "retry",
        "Rate limiting was resolved by exponential backoff. "
        "Reusable lesson: retry transient failures with exponential backoff.",
        ["backoff"],
        True,
    ),
    (
        "lease",
        "Duplicate job processing was avoided by fencing writes with the lease owner. "
        "Reusable lesson: check the job lease before committing writes.",
        ["lease"],
        True,
    ),
    (
        "tenant",
        "A cross-tenant data access bug was fixed by applying the tenant filter before ranking. "
        "Reusable lesson: filter by tenant before retrieval ranking.",
        ["tenant"],
        True,
    ),
    ("chinese", "部署失败后检查配置文件解决问题，以后部署前应该核对配置。", ["配置"], True),
    ("empty", "No reusable lesson is present; this is only a greeting: hello.", [], False),
    ("sensitive-key", "API_KEY=fake-evaluation-placeholder", [], False),
    ("sensitive-email", "Contact alice@example.test", [], False),
    ("sensitive-id", "身份证 11010519491231002X", [], False),
    ("sensitive-card", "卡号 4111 1111 1111 1111", [], False),
]


async def main() -> None:
    values = dict(
        line.split("=", 1)
        for line in Path(".local/ark.env").read_text().splitlines()
        if "=" in line and not line.startswith("#")
    )
    model = values.get("MEMORY_EXTRACTION_MODEL", "doubao-seed-2-0-mini-260428")
    rows = []
    async with httpx.AsyncClient(trust_env=False, timeout=15) as client:
        extractor = LLMExtractor(
            "https://ark.cn-beijing.volces.com/api/v3/chat/completions",
            model,
            values["ARK_API_KEY"],
            client=client,
        )
        for name, summary, terms, expected in CASES:
            at = datetime.now(UTC)
            event = Event(
                uuid4(),
                uuid4(),
                EventDraft(
                    name,
                    name,
                    1,
                    EventType.TASK_COMPLETED,
                    "eval",
                    at,
                    MemoryScope(ScopeKind.WORKSPACE, "synthetic-eval", None),
                    {"summary": summary},
                ),
                uuid4(),
                at,
            )
            candidates = ()
            failure = None
            for attempt in range(5):
                try:
                    candidates = await extractor.extract(event)
                    break
                except RetryableExtractionError as error:
                    failure = error.code
                    if attempt < 4:
                        await asyncio.sleep(min(2 ** (attempt + 1), 8))
            text = " ".join(c.content for c in candidates).lower()
            rows.append(
                {
                    "id": name,
                    "expected_candidate": expected,
                    "candidate_count": len(candidates),
                    "reason": extractor.last_reason,
                    "last_transient_error": failure,
                    "scope_preserved": all(c.scope == event.draft.scope for c in candidates),
                    "term_coverage": all(term in text for term in terms)
                    if expected
                    else not candidates,
                }
            )
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "model": model,
        "cases": rows,
        "limits": "12 synthetic labeled samples; exact term coverage heuristic, not human score",
        "candidate_presence_correct": sum(
            bool(r["candidate_count"]) == r["expected_candidate"] for r in rows
        ),
        "term_coverage_passed": sum(r["term_coverage"] for r in rows),
    }
    Path("docs/measurements/hardening-extraction-real.json").write_text(
        json.dumps(report, indent=2) + "\n"
    )
    print(json.dumps({k: v for k, v in report.items() if k != "cases"}))


asyncio.run(main())
