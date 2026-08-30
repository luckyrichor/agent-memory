from dataclasses import dataclass
from uuid import UUID

from agent_memory.domain.enums import MemoryStatus, MemoryType
from agent_memory.domain.models import MemoryScope


@dataclass(frozen=True, slots=True)
class RememberMemoryCommand:
    content: str
    memory_type: MemoryType
    scope: MemoryScope
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class CorrectMemoryCommand:
    memory_id: UUID
    expected_revision: int
    content: str
    reason: str


@dataclass(frozen=True, slots=True)
class DisableMemoryCommand:
    memory_id: UUID
    expected_revision: int
    status: MemoryStatus


@dataclass(frozen=True, slots=True)
class MemoryResult:
    memory_id: UUID
    version_id: UUID
    revision: int
    status: MemoryStatus
