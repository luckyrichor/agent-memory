from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError

from agent_memory.application.ports import AuditEntry
from agent_memory.domain.enums import MemoryType, ScopeKind
from agent_memory.domain.models import Memory, MemoryScope
from agent_memory.domain.principal import RequestPrincipal
from agent_memory.infrastructure.db import (
    create_engine,
    create_session_factory,
    session_for_principal,
)
from agent_memory.infrastructure.orm import (
    AuditLogRow,
    EventRow,
    EvidenceRow,
    JobRow,
    MemoryRow,
    MemoryVersionRow,
    OutboxMessageRow,
)
from agent_memory.infrastructure.repositories import PostgresAuditSink, PostgresMemoryRepository

TENANT_A = UUID("10000000-0000-0000-0000-00000000000a")
TENANT_B = UUID("20000000-0000-0000-0000-00000000000b")
USER_A = UUID("10000000-0000-0000-0000-000000000001")
USER_B = UUID("20000000-0000-0000-0000-000000000002")
MEMORY_ID = UUID("10000000-0000-0000-0000-000000000003")
VERSION_ID = UUID("10000000-0000-0000-0000-000000000004")
NOW = datetime(2026, 8, 30, 15, 0, tzinfo=UTC)
PIPELINE_MEMORY_ID = UUID("10000000-0000-0000-0000-000000000013")
PIPELINE_VERSION_ID = UUID("10000000-0000-0000-0000-000000000014")
EVENT_ID = UUID("10000000-0000-0000-0000-000000000015")
OUTBOX_ID = UUID("10000000-0000-0000-0000-000000000016")
JOB_ID = UUID("10000000-0000-0000-0000-000000000017")


def principal(tenant_id: UUID, user_id: UUID) -> RequestPrincipal:
    return RequestPrincipal(
        tenant_id=tenant_id,
        user_id=user_id,
        roles=frozenset({"developer"}),
        permissions=frozenset({"memory:read", "memory:write"}),
        allowed_workspace_ids=frozenset({"project-a"}),
    )


@pytest.mark.asyncio
async def test_known_id_cannot_cross_tenant_read_update_link_or_audit(
    app_database_url: str,
) -> None:
    engine = create_engine(app_database_url)
    sessions = create_session_factory(engine)
    tenant_a = principal(TENANT_A, USER_A)
    tenant_b = principal(TENANT_B, USER_B)
    memory, version = Memory.create(
        tenant_id=TENANT_A,
        memory_id=MEMORY_ID,
        version_id=VERSION_ID,
        memory_type=MemoryType.EPISODIC,
        scope=MemoryScope(ScopeKind.WORKSPACE, "project-a", None),
        owner_user_id=USER_A,
        content="Tenant A private build memory",
        now=NOW,
    )

    async with session_for_principal(sessions, tenant_a) as session:
        await PostgresMemoryRepository(session).add(TENANT_A, memory, version)
        await PostgresAuditSink(session, new_id=uuid4, now=lambda: NOW).record(
            AuditEntry(
                tenant_id=TENANT_A,
                actor_id=USER_A,
                action="memory.remember",
                decision="allow",
                reason_code="MEMORY_CREATED",
                resource_id=MEMORY_ID,
            )
        )

    async with session_for_principal(sessions, tenant_b) as session:
        assert await PostgresMemoryRepository(session).get(TENANT_B, MEMORY_ID) is None
        update_result = await session.execute(
            update(MemoryRow)
            .where(MemoryRow.tenant_id == TENANT_A, MemoryRow.memory_id == MEMORY_ID)
            .values(status="deleted")
        )
        assert update_result.rowcount == 0
        audit_ids = (
            await session.execute(select(AuditLogRow.audit_id).where(AuditLogRow.tenant_id == TENANT_A))
        ).scalars()
        assert list(audit_ids) == []

    with pytest.raises(IntegrityError):
        async with session_for_principal(sessions, tenant_b) as session:
            await session.execute(
                text(
                    "INSERT INTO memory_versions "
                    "(tenant_id, memory_version_id, memory_id, version_number, content, "
                    "structured_content, content_hash, confidence, utility, authority_level, "
                    "verification_status, created_at) VALUES "
                    "(:tenant_id, :version_id, :memory_id, 2, 'forged', '{}'::jsonb, "
                    ":content_hash, 1, 1, 0, 'unverified', :created_at)"
                ),
                {
                    "tenant_id": str(TENANT_B),
                    "version_id": str(UUID("20000000-0000-0000-0000-000000000005")),
                    "memory_id": str(MEMORY_ID),
                    "content_hash": "0" * 64,
                    "created_at": NOW,
                },
            )

    async with session_for_principal(sessions, tenant_a) as session:
        still_active = await session.scalar(
            select(MemoryRow.status).where(
                MemoryRow.tenant_id == TENANT_A,
                MemoryRow.memory_id == MEMORY_ID,
            )
        )
        version_count = len(
            list(
                (
                    await session.execute(
                        select(MemoryVersionRow.memory_version_id).where(
                            MemoryVersionRow.tenant_id == TENANT_A,
                            MemoryVersionRow.memory_id == MEMORY_ID,
                        )
                    )
                ).scalars()
            )
        )

    assert still_active == "active"
    assert version_count == 1
    await engine.dispose()


@pytest.mark.asyncio
async def test_event_pipeline_known_ids_are_isolated_by_tenant(
    app_database_url: str,
) -> None:
    engine = create_engine(app_database_url)
    sessions = create_session_factory(engine)
    tenant_a = principal(TENANT_A, USER_A)
    tenant_b = principal(TENANT_B, USER_B)
    memory, version = Memory.create(
        tenant_id=TENANT_A,
        memory_id=PIPELINE_MEMORY_ID,
        version_id=PIPELINE_VERSION_ID,
        memory_type=MemoryType.EPISODIC,
        scope=MemoryScope(ScopeKind.WORKSPACE, "project-a", None),
        owner_user_id=USER_A,
        content="private pipeline memory",
        now=NOW,
    )

    async with session_for_principal(sessions, tenant_a) as session:
        await PostgresMemoryRepository(session).add(TENANT_A, memory, version)
        session.add_all(
            [
                EventRow(
                    tenant_id=TENANT_A,
                    event_id=EVENT_ID,
                    idempotency_key="pipeline-event-a",
                    request_hash="1" * 64,
                    session_id="pipeline-session-a",
                    sequence_number=1,
                    event_type="tool.result",
                    scope_kind="workspace",
                    workspace_id="project-a",
                    subject_user_id=None,
                    actor_user_id=USER_A,
                    agent_id="coding_agent",
                    occurred_at=NOW,
                    received_at=NOW,
                    payload={"tool_name": "build", "exit_code": 1},
                ),
                OutboxMessageRow(
                    tenant_id=TENANT_A,
                    outbox_id=OUTBOX_ID,
                    topic="event.recorded",
                    aggregate_type="event",
                    aggregate_id=EVENT_ID,
                    payload={"event_id": str(EVENT_ID)},
                    status="pending",
                    available_at=NOW,
                    attempts=0,
                    created_at=NOW,
                    published_at=None,
                ),
                JobRow(
                    tenant_id=TENANT_A,
                    job_id=JOB_ID,
                    job_type="extract_event",
                    idempotency_key=f"extract:{EVENT_ID}:v1",
                    payload={"event_id": str(EVENT_ID), "extractor_version": "v1"},
                    status="pending",
                    attempts=0,
                    max_attempts=5,
                    available_at=NOW,
                    leased_until=None,
                    lease_owner=None,
                    last_error_code=None,
                    created_at=NOW,
                    updated_at=NOW,
                ),
                EvidenceRow(
                    tenant_id=TENANT_A,
                    memory_version_id=PIPELINE_VERSION_ID,
                    event_id=EVENT_ID,
                    role="triggered_by",
                    created_at=NOW,
                ),
            ]
        )

    async with session_for_principal(sessions, tenant_b) as session:
        assert list((await session.execute(select(EventRow.event_id))).scalars()) == []
        assert list((await session.execute(select(OutboxMessageRow.outbox_id))).scalars()) == []
        assert list((await session.execute(select(JobRow.job_id))).scalars()) == []
        assert list((await session.execute(select(EvidenceRow.event_id))).scalars()) == []
        changed = await session.execute(
            update(JobRow).where(JobRow.job_id == JOB_ID).values(status="dead")
        )
        assert changed.rowcount == 0

    with pytest.raises(IntegrityError):
        async with session_for_principal(sessions, tenant_b) as session:
            session.add(
                EvidenceRow(
                    tenant_id=TENANT_B,
                    memory_version_id=PIPELINE_VERSION_ID,
                    event_id=EVENT_ID,
                    role="triggered_by",
                    created_at=NOW,
                )
            )
            await session.flush()

    async with session_for_principal(sessions, tenant_a) as session:
        assert await session.scalar(select(JobRow.status).where(JobRow.job_id == JOB_ID)) == "pending"
        assert await session.scalar(
            select(EvidenceRow.event_id).where(EvidenceRow.event_id == EVENT_ID)
        ) == EVENT_ID

    await engine.dispose()
