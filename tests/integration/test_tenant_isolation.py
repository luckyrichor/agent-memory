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
from agent_memory.infrastructure.orm import AuditLogRow, MemoryRow, MemoryVersionRow
from agent_memory.infrastructure.repositories import PostgresAuditSink, PostgresMemoryRepository

TENANT_A = UUID("10000000-0000-0000-0000-00000000000a")
TENANT_B = UUID("20000000-0000-0000-0000-00000000000b")
USER_A = UUID("10000000-0000-0000-0000-000000000001")
USER_B = UUID("20000000-0000-0000-0000-000000000002")
MEMORY_ID = UUID("10000000-0000-0000-0000-000000000003")
VERSION_ID = UUID("10000000-0000-0000-0000-000000000004")
NOW = datetime(2026, 8, 30, 15, 0, tzinfo=UTC)


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
