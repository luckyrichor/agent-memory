from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import func, select

from agent_memory.application.extraction import CodingFailureRuleExtractor
from agent_memory.application.extraction_worker import ExtractionWorker
from agent_memory.domain.enums import ScopeKind
from agent_memory.domain.events import EventDraft, EventType
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
from agent_memory.infrastructure.orm import (
    EventRow,
    EvidenceRow,
    JobRow,
    MemoryRow,
    MemoryVersionRow,
    OutboxMessageRow,
)

TENANT_ID = UUID("35000000-0000-0000-0000-000000000001")
USER_ID = UUID("35000000-0000-0000-0000-000000000002")
NOW = datetime(2026, 8, 30, 19, 0, tzinfo=UTC)


def ids() -> Iterator[UUID]:
    number = 10
    while True:
        yield UUID(f"35000000-0000-0000-0000-{number:012d}")
        number += 1


def principal() -> RequestPrincipal:
    return RequestPrincipal(
        tenant_id=TENANT_ID,
        user_id=USER_ID,
        roles=frozenset({"developer"}),
        permissions=frozenset({"memory:read", "memory:write"}),
        allowed_workspace_ids=frozenset({"project-a"}),
    )


def build_failure() -> EventDraft:
    return EventDraft(
        idempotency_key="e2e-build-failure",
        session_id="e2e-session",
        sequence_number=1,
        event_type=EventType.TOOL_RESULT,
        agent_id="coding_agent",
        occurred_at=NOW,
        scope=MemoryScope(ScopeKind.WORKSPACE, "project-a", None),
        payload={
            "tool_name": "build",
            "exit_code": 1,
            "summary": "x86_64 dependency failed on arm64",
        },
    )


@pytest.mark.asyncio
async def test_duplicate_failure_event_produces_one_complete_candidate_lineage(
    app_database_url: str,
) -> None:
    engine = create_engine(app_database_url)
    sessions = create_session_factory(engine)
    id_values = ids()
    async with session_for_principal(sessions, principal()) as session:
        ingestion = PostgresEventIngestionRepository(
            session, new_id=lambda: next(id_values), now=lambda: NOW
        )
        first = await ingestion.ingest_batch(TENANT_ID, USER_ID, (build_failure(),))
        replay = await ingestion.ingest_batch(TENANT_ID, USER_ID, (build_failure(),))
        assert replay[0].event_id == first[0].event_id

    async with session_for_principal(sessions, principal()) as session:
        dispatcher = PostgresOutboxRepository(
            session, new_id=lambda: next(id_values), now=lambda: NOW
        )
        assert await dispatcher.dispatch_once(TENANT_ID, 10, "coding-failure-rule-v1") == 1

    backend = PostgresExtractionBackend(
        sessions,
        new_id=lambda: next(id_values),
        now=lambda: NOW,
    )
    worker = ExtractionWorker(
        backend,
        CodingFailureRuleExtractor(),
        now=lambda: NOW,
        lease_duration=timedelta(seconds=30),
    )
    processed = await worker.run_once(TENANT_ID, "worker-e2e")
    empty = await worker.run_once(TENANT_ID, "worker-e2e")

    async with session_for_principal(sessions, principal()) as session:
        counts = {
            "events": await session.scalar(select(func.count()).select_from(EventRow)),
            "outbox": await session.scalar(select(func.count()).select_from(OutboxMessageRow)),
            "jobs": await session.scalar(select(func.count()).select_from(JobRow)),
            "memories": await session.scalar(select(func.count()).select_from(MemoryRow)),
            "versions": await session.scalar(select(func.count()).select_from(MemoryVersionRow)),
            "evidence": await session.scalar(select(func.count()).select_from(EvidenceRow)),
        }
        job_status = await session.scalar(select(JobRow.status))
        memory_status = await session.scalar(select(MemoryRow.status))

    assert processed.outcome == "succeeded"
    assert empty.outcome == "no_job"
    assert counts == {
        "events": 1,
        "outbox": 1,
        "jobs": 1,
        "memories": 1,
        "versions": 1,
        "evidence": 1,
    }
    assert job_status == "succeeded"
    assert memory_status == "candidate"
    await engine.dispose()
