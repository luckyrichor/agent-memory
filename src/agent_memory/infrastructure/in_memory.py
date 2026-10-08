from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

from agent_memory.application.ports import (
    AuditEntry,
    IdempotencyRecord,
    MemoryRecord,
)
from agent_memory.domain.errors import MemoryNotFound, RevisionConflict
from agent_memory.domain.models import Memory, MemoryVersion


class InMemoryMemoryRepository:
    def __init__(self) -> None:
        self._records: dict[tuple[UUID, UUID], MemoryRecord] = {}

    @property
    def count(self) -> int:
        return len(self._records)

    async def add(self, tenant_id: UUID, memory: Memory, version: MemoryVersion) -> None:
        self._records[(tenant_id, memory.memory_id)] = MemoryRecord(memory, (version,))

    async def get(self, tenant_id: UUID, memory_id: UUID) -> MemoryRecord | None:
        record = self._records.get((tenant_id, memory_id))
        return replace(record, versions=(record.current_version,)) if record else None

    async def versions(
        self, tenant_id: UUID, memory_id: UUID, limit: int, offset: int
    ) -> tuple[MemoryVersion, ...]:
        record = self._records.get((tenant_id, memory_id))
        return record.versions[offset : offset + limit] if record else ()

    async def append_version(
        self,
        tenant_id: UUID,
        memory: Memory,
        version: MemoryVersion,
        expected_revision: int,
    ) -> None:
        key = (tenant_id, memory.memory_id)
        record = self._records.get(key)
        if record is None:
            raise MemoryNotFound(str(memory.memory_id))
        if record.memory.revision != expected_revision:
            raise RevisionConflict(
                f"expected revision {expected_revision}, current revision {record.memory.revision}"
            )
        self._records[key] = MemoryRecord(memory, (*record.versions, version))

    async def disable(
        self,
        tenant_id: UUID,
        memory: Memory,
        expected_revision: int,
    ) -> None:
        key = (tenant_id, memory.memory_id)
        record = self._records.get(key)
        if record is None:
            raise MemoryNotFound(str(memory.memory_id))
        if record.memory.revision != expected_revision:
            raise RevisionConflict(
                f"expected revision {expected_revision}, current revision {record.memory.revision}"
            )
        self._records[key] = replace(record, memory=memory)


class InMemoryIdempotencyRepository:
    def __init__(self, now: Callable[[], datetime] | None = None) -> None:
        self._now = now or (lambda: datetime.now(UTC))
        self._created: dict[tuple[UUID, str], datetime] = {}
        self._records: dict[tuple[UUID, str], IdempotencyRecord] = {}

    async def lock(self, tenant_id: UUID, key: str) -> None:
        # Methods in this adapter do not suspend; operations run atomically in one loop.
        pass

    async def get(self, tenant_id: UUID, key: str) -> IdempotencyRecord | None:
        identity = (tenant_id, key)
        if identity in self._created and self._created[identity] <= self._now() - timedelta(days=7):
            self._records.pop(identity, None)
            self._created.pop(identity, None)
        return self._records.get(identity)

    async def save(self, tenant_id: UUID, key: str, record: IdempotencyRecord) -> None:
        self._records[(tenant_id, key)] = record
        self._created[(tenant_id, key)] = self._now()


class InMemoryAuditSink:
    def __init__(self) -> None:
        self.entries: list[AuditEntry] = []

    async def record(self, entry: AuditEntry) -> None:
        self.entries.append(entry)
