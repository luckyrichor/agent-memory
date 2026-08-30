import hashlib
from collections.abc import Callable
from datetime import datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import CursorResult, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from agent_memory.application.commands import MemoryResult
from agent_memory.application.ports import AuditEntry, IdempotencyRecord, MemoryRecord
from agent_memory.domain.enums import (
    AuthorityLevel,
    MemoryStatus,
    MemoryType,
    ScopeKind,
    VerificationStatus,
)
from agent_memory.domain.errors import MemoryNotFound, RevisionConflict
from agent_memory.domain.models import Memory, MemoryScope, MemoryVersion
from agent_memory.infrastructure.orm import (
    AuditLogRow,
    IdempotencyRecordRow,
    MemoryRow,
    MemoryVersionRow,
)


class PostgresMemoryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, tenant_id: UUID, memory: Memory, version: MemoryVersion) -> None:
        self._session.add(self._memory_row(memory))
        self._session.add(self._version_row(version))
        await self._session.flush()

    async def get(self, tenant_id: UUID, memory_id: UUID) -> MemoryRecord | None:
        memory_row = await self._session.scalar(
            select(MemoryRow).where(
                MemoryRow.tenant_id == tenant_id,
                MemoryRow.memory_id == memory_id,
            )
        )
        if memory_row is None:
            return None
        version_rows = (
            await self._session.scalars(
                select(MemoryVersionRow)
                .where(
                    MemoryVersionRow.tenant_id == tenant_id,
                    MemoryVersionRow.memory_id == memory_id,
                )
                .order_by(MemoryVersionRow.version_number)
            )
        ).all()
        return MemoryRecord(
            memory=self._memory_domain(memory_row),
            versions=tuple(self._version_domain(row) for row in version_rows),
        )

    async def append_version(
        self,
        tenant_id: UUID,
        memory: Memory,
        version: MemoryVersion,
        expected_revision: int,
    ) -> None:
        result = cast(
            CursorResult[Any],
            await self._session.execute(
                update(MemoryRow)
                .where(
                    MemoryRow.tenant_id == tenant_id,
                    MemoryRow.memory_id == memory.memory_id,
                    MemoryRow.revision == expected_revision,
                )
                .values(
                    current_version_id=memory.current_version_id,
                    revision=memory.revision,
                    updated_at=memory.updated_at,
                )
            ),
        )
        if result.rowcount != 1:
            await self._raise_missing_or_conflict(tenant_id, memory.memory_id, expected_revision)
        self._session.add(self._version_row(version))
        await self._session.flush()

    async def disable(
        self,
        tenant_id: UUID,
        memory: Memory,
        expected_revision: int,
    ) -> None:
        result = cast(
            CursorResult[Any],
            await self._session.execute(
                update(MemoryRow)
                .where(
                    MemoryRow.tenant_id == tenant_id,
                    MemoryRow.memory_id == memory.memory_id,
                    MemoryRow.revision == expected_revision,
                )
                .values(
                    status=memory.status.value,
                    revision=memory.revision,
                    updated_at=memory.updated_at,
                    disabled_at=memory.disabled_at,
                )
            ),
        )
        if result.rowcount != 1:
            await self._raise_missing_or_conflict(tenant_id, memory.memory_id, expected_revision)

    async def _raise_missing_or_conflict(
        self,
        tenant_id: UUID,
        memory_id: UUID,
        expected_revision: int,
    ) -> None:
        current_revision = await self._session.scalar(
            select(MemoryRow.revision).where(
                MemoryRow.tenant_id == tenant_id,
                MemoryRow.memory_id == memory_id,
            )
        )
        if current_revision is None:
            raise MemoryNotFound(str(memory_id))
        raise RevisionConflict(
            f"expected revision {expected_revision}, current revision {current_revision}"
        )

    @staticmethod
    def _memory_row(memory: Memory) -> MemoryRow:
        return MemoryRow(
            tenant_id=memory.tenant_id,
            memory_id=memory.memory_id,
            memory_type=memory.memory_type.value,
            status=memory.status.value,
            scope_kind=memory.scope.kind.value,
            workspace_id=memory.scope.workspace_id,
            subject_user_id=memory.scope.subject_user_id,
            visibility="scope",
            owner_user_id=memory.owner_user_id,
            current_version_id=memory.current_version_id,
            revision=memory.revision,
            created_at=memory.created_at,
            updated_at=memory.updated_at,
            disabled_at=memory.disabled_at,
        )

    @staticmethod
    def _version_row(version: MemoryVersion) -> MemoryVersionRow:
        return MemoryVersionRow(
            tenant_id=version.tenant_id,
            memory_version_id=version.version_id,
            memory_id=version.memory_id,
            version_number=version.version_number,
            content=version.content,
            structured_content=dict(version.structured_content),
            content_hash=hashlib.sha256(version.content.encode()).hexdigest(),
            confidence=version.confidence,
            utility=version.utility,
            authority_level=int(version.authority_level),
            verification_status=version.verification_status.value,
            created_at=version.created_at,
        )

    @staticmethod
    def _memory_domain(row: MemoryRow) -> Memory:
        if row.current_version_id is None:
            raise RuntimeError("persisted memory has no current version")
        return Memory(
            tenant_id=row.tenant_id,
            memory_id=row.memory_id,
            memory_type=MemoryType(row.memory_type),
            status=MemoryStatus(row.status),
            scope=MemoryScope(
                ScopeKind(row.scope_kind),
                row.workspace_id,
                row.subject_user_id,
            ),
            owner_user_id=row.owner_user_id,
            current_version_id=row.current_version_id,
            revision=row.revision,
            created_at=row.created_at,
            updated_at=row.updated_at,
            disabled_at=row.disabled_at,
        )

    @staticmethod
    def _version_domain(row: MemoryVersionRow) -> MemoryVersion:
        return MemoryVersion(
            tenant_id=row.tenant_id,
            version_id=row.memory_version_id,
            memory_id=row.memory_id,
            version_number=row.version_number,
            content=row.content,
            structured_content=row.structured_content,
            confidence=row.confidence,
            utility=row.utility,
            authority_level=AuthorityLevel(row.authority_level),
            verification_status=VerificationStatus(row.verification_status),
            created_at=row.created_at,
        )


class PostgresIdempotencyRepository:
    def __init__(self, session: AsyncSession, now: Callable[[], datetime]) -> None:
        self._session = session
        self._now = now

    async def get(self, tenant_id: UUID, key: str) -> IdempotencyRecord | None:
        row = await self._session.scalar(
            select(IdempotencyRecordRow).where(
                IdempotencyRecordRow.tenant_id == tenant_id,
                IdempotencyRecordRow.idempotency_key == key,
            )
        )
        if row is None:
            return None
        result = row.result_json
        return IdempotencyRecord(
            request_hash=row.request_hash,
            result=MemoryResult(
                memory_id=UUID(result["memory_id"]),
                version_id=UUID(result["version_id"]),
                revision=int(result["revision"]),
                status=MemoryStatus(result["status"]),
            ),
        )

    async def save(self, tenant_id: UUID, key: str, record: IdempotencyRecord) -> None:
        self._session.add(
            IdempotencyRecordRow(
                tenant_id=tenant_id,
                idempotency_key=key,
                request_hash=record.request_hash,
                result_json={
                    "memory_id": str(record.result.memory_id),
                    "version_id": str(record.result.version_id),
                    "revision": record.result.revision,
                    "status": record.result.status.value,
                },
                created_at=self._now(),
            )
        )
        await self._session.flush()


class PostgresAuditSink:
    def __init__(
        self,
        session: AsyncSession,
        *,
        new_id: Callable[[], UUID],
        now: Callable[[], datetime],
    ) -> None:
        self._session = session
        self._new_id = new_id
        self._now = now

    async def record(self, entry: AuditEntry) -> None:
        self._session.add(
            AuditLogRow(
                tenant_id=entry.tenant_id,
                audit_id=self._new_id(),
                actor_id=entry.actor_id,
                action=entry.action,
                decision=entry.decision,
                reason_code=entry.reason_code,
                resource_id=entry.resource_id,
                metadata_json={},
                occurred_at=self._now(),
            )
        )
        await self._session.flush()
