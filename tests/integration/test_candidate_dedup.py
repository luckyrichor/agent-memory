"""E2: an extracted candidate that repeats a live memory adds evidence, not a new memory."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from itertools import count
from uuid import UUID

import pytest
from sqlalchemy import func, select, update

from agent_memory.application.extraction import CodingFailureRuleExtractor
from agent_memory.application.extraction_worker import ExtractionWorker
from agent_memory.domain.activation import ActivationMode
from agent_memory.domain.enums import MemoryStatus, ScopeKind
from agent_memory.domain.events import EventDraft, EventType, MemoryCandidate
from agent_memory.domain.models import MemoryScope
from agent_memory.domain.principal import RequestPrincipal
from agent_memory.infrastructure.db import (
    create_engine,
    create_session_factory,
    session_for_principal,
)
from agent_memory.infrastructure.event_repositories import (
    PostgresEventIngestionRepository,
    PostgresExtractionBackend,
    PostgresOutboxRepository,
)
from agent_memory.infrastructure.orm import EvidenceRow, MemoryRow, MemoryVersionRow

USER_ID = UUID("3b000000-0000-0000-0000-000000000002")
NOW = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
TEXT = "dependency conflict on arm64 resolved by pinning protobuf"
_counter = count(1)


def ids() -> Iterator[UUID]:
    for number in _counter:
        yield UUID(f"3b100000-0000-0000-0000-{number:012d}")


def principal(tenant_id: UUID) -> RequestPrincipal:
    return RequestPrincipal(
        tenant_id, USER_ID, frozenset({"developer"}), frozenset({"memory:write"}),
        frozenset({"project-a", "project-b"}),
    )


class TwiceExtractor:
    """One event yielding the same candidate twice."""

    version = "coding-failure-rule-v1"  # must match the version the outbox job was created for

    async def extract(self, event: object) -> tuple[MemoryCandidate, ...]:
        one = await CodingFailureRuleExtractor().extract(event)  # type: ignore[arg-type]
        return one + one


async def run_event(
    sessions: object,
    tenant_id: UUID,
    key: str,
    summary: str,
    workspace: str = "project-a",
    mode: ActivationMode = "auto",
    extractor: object | None = None,
) -> None:
    generator = ids()
    sessions_ = sessions  # type: ignore[assignment]
    draft = EventDraft(
        idempotency_key=f"e2-{key}", session_id=f"e2-session-{key}", sequence_number=1,
        event_type=EventType.TOOL_RESULT, agent_id="coding_agent", occurred_at=NOW,
        scope=MemoryScope(ScopeKind.WORKSPACE, workspace, None),
        payload={"tool_name": "test", "exit_code": 1, "summary": summary},
    )
    async with session_for_principal(sessions_, principal(tenant_id)) as session:  # type: ignore[arg-type]
        await PostgresEventIngestionRepository(
            session, new_id=lambda: next(generator), now=lambda: NOW
        ).ingest_batch(tenant_id, USER_ID, (draft,))
    async with session_for_principal(sessions_, principal(tenant_id)) as session:  # type: ignore[arg-type]
        await PostgresOutboxRepository(
            session, new_id=lambda: next(generator), now=lambda: NOW
        ).dispatch_once(tenant_id, 10, "coding-failure-rule-v1")
    worker = ExtractionWorker(
        PostgresExtractionBackend(
            sessions_, new_id=lambda: next(generator), now=lambda: NOW, activation=mode  # type: ignore[arg-type]
        ),
        extractor or CodingFailureRuleExtractor(),  # type: ignore[arg-type]
        now=lambda: NOW,
        lease_duration=timedelta(seconds=30),
    )
    assert (await worker.run_once(tenant_id, "e2-worker")).outcome == "succeeded"


async def memories(sessions: object, tenant_id: UUID) -> list[tuple[UUID, str, str | None]]:
    async with session_for_principal(sessions, principal(tenant_id)) as session:  # type: ignore[arg-type]
        rows = await session.execute(
            select(MemoryRow.memory_id, MemoryRow.status, MemoryRow.workspace_id)
            .order_by(MemoryRow.created_at, MemoryRow.memory_id)
        )
        return [(a, b, c) for a, b, c in rows.all()]


async def evidence(sessions: object, tenant_id: UUID, memory_id: UUID) -> list[tuple[str, str]]:
    async with session_for_principal(sessions, principal(tenant_id)) as session:  # type: ignore[arg-type]
        rows = await session.execute(
            select(EvidenceRow.role, func.count())
            .join(
                MemoryVersionRow,
                (MemoryVersionRow.tenant_id == EvidenceRow.tenant_id)
                & (MemoryVersionRow.memory_version_id == EvidenceRow.memory_version_id),
            )
            .where(MemoryVersionRow.memory_id == memory_id)
            .group_by(EvidenceRow.role)
            .order_by(EvidenceRow.role)
        )
        return [(role, int(n)) for role, n in rows.all()]


@pytest.mark.asyncio
async def test_repeats_add_evidence_and_distinct_texts_scopes_or_dead_memories_do_not(
    app_database_url: str,
) -> None:
    from uuid import uuid4

    tenant_id = uuid4()
    engine = create_engine(app_database_url)
    sessions = create_session_factory(engine)
    try:
        await run_event(sessions, tenant_id, "1", TEXT)
        first = await memories(sessions, tenant_id)
        assert len(first) == 1 and first[0][1] == "active"
        assert await evidence(sessions, tenant_id, first[0][0]) == [("triggered_by", 1)]

        # Same text up to case and whitespace: no new memory, one more evidence row.
        await run_event(sessions, tenant_id, "2", "  Dependency  CONFLICT on arm64 resolved "
                        "by pinning PROTOBUF ")
        assert [m[0] for m in await memories(sessions, tenant_id)] == [first[0][0]]
        assert await evidence(sessions, tenant_id, first[0][0]) == [
            ("supports", 1), ("triggered_by", 1),
        ]

        # Same text, other workspace: a different scope is a different memory.
        await run_event(sessions, tenant_id, "3", TEXT, workspace="project-b")
        assert len(await memories(sessions, tenant_id)) == 2

        # Punctuation is NOT normalized: documented limit of exact-duplicate matching.
        await run_event(sessions, tenant_id, "4", TEXT + ".")
        assert len(await memories(sessions, tenant_id)) == 3

        # A deleted memory does not absorb new evidence: re-extraction creates a fresh one.
        async with session_for_principal(sessions, principal(tenant_id)) as session:
            await session.execute(
                update(MemoryRow)
                .where(MemoryRow.tenant_id == tenant_id, MemoryRow.memory_id == first[0][0])
                .values(status=MemoryStatus.DELETED.value)
            )
        await run_event(sessions, tenant_id, "5", TEXT)
        after = await memories(sessions, tenant_id)
        assert len(after) == 4
        assert await evidence(sessions, tenant_id, first[0][0]) == [
            ("supports", 1), ("triggered_by", 1),
        ]
        assert after[-1][1] == "active" and after[-1][0] != first[0][0]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_manual_mode_candidates_dedupe_and_one_event_cannot_duplicate_itself(
    app_database_url: str,
) -> None:
    from uuid import uuid4

    tenant_id = uuid4()
    engine = create_engine(app_database_url)
    sessions = create_session_factory(engine)
    try:
        await run_event(sessions, tenant_id, "m1", TEXT, mode="manual")
        await run_event(sessions, tenant_id, "m2", TEXT.upper(), mode="manual")
        rows = await memories(sessions, tenant_id)
        assert [r[1] for r in rows] == ["candidate"]  # still just one, still awaiting review

        other = uuid4()
        await run_event(sessions, other, "t1", TEXT, extractor=TwiceExtractor())
        only = await memories(sessions, other)
        assert len(only) == 1
        # The event is already linked as triggered_by; the repeat adds no second link.
        assert await evidence(sessions, other, only[0][0]) == [("triggered_by", 1)]
    finally:
        await engine.dispose()
