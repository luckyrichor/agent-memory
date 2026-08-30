from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from agent_memory.application.commands import MemoryResult
from agent_memory.domain.models import Memory, MemoryVersion


@dataclass(frozen=True, slots=True)
class MemoryRecord:
    memory: Memory
    versions: tuple[MemoryVersion, ...]

    @property
    def current_version(self) -> MemoryVersion:
        for version in reversed(self.versions):
            if version.version_id == self.memory.current_version_id:
                return version
        raise RuntimeError("current memory version is missing")


@dataclass(frozen=True, slots=True)
class IdempotencyRecord:
    request_hash: str
    result: MemoryResult


@dataclass(frozen=True, slots=True)
class AuditEntry:
    tenant_id: UUID
    actor_id: UUID
    action: str
    decision: str
    reason_code: str
    resource_id: UUID | None


class MemoryRepository(Protocol):
    async def add(self, tenant_id: UUID, memory: Memory, version: MemoryVersion) -> None: ...

    async def get(self, tenant_id: UUID, memory_id: UUID) -> MemoryRecord | None: ...

    async def append_version(
        self,
        tenant_id: UUID,
        memory: Memory,
        version: MemoryVersion,
        expected_revision: int,
    ) -> None: ...

    async def disable(
        self,
        tenant_id: UUID,
        memory: Memory,
        expected_revision: int,
    ) -> None: ...


class IdempotencyRepository(Protocol):
    async def get(self, tenant_id: UUID, key: str) -> IdempotencyRecord | None: ...

    async def save(self, tenant_id: UUID, key: str, record: IdempotencyRecord) -> None: ...


class AuditSink(Protocol):
    async def record(self, entry: AuditEntry) -> None: ...
