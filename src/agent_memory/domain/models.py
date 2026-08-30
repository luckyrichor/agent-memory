from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from types import MappingProxyType
from uuid import UUID

from agent_memory.domain.enums import (
    AuthorityLevel,
    MemoryStatus,
    MemoryType,
    ScopeKind,
    VerificationStatus,
)
from agent_memory.domain.errors import InvalidScope, InvalidStatusTransition, RevisionConflict


@dataclass(frozen=True, slots=True)
class MemoryScope:
    kind: ScopeKind
    workspace_id: str | None
    subject_user_id: UUID | None

    def __post_init__(self) -> None:
        valid = {
            ScopeKind.TENANT: self.workspace_id is None and self.subject_user_id is None,
            ScopeKind.WORKSPACE: self.workspace_id is not None and self.subject_user_id is None,
            ScopeKind.USER_GLOBAL: self.workspace_id is None and self.subject_user_id is not None,
            ScopeKind.USER_WORKSPACE: (
                self.workspace_id is not None and self.subject_user_id is not None
            ),
        }
        if not valid[self.kind]:
            raise InvalidScope(
                f"invalid {self.kind.value} scope: "
                f"workspace_id={self.workspace_id!r}, subject_user_id={self.subject_user_id!r}"
            )


@dataclass(frozen=True, slots=True)
class MemoryVersion:
    tenant_id: UUID
    version_id: UUID
    memory_id: UUID
    version_number: int
    content: str
    structured_content: Mapping[str, object]
    confidence: float
    utility: float
    authority_level: AuthorityLevel
    verification_status: VerificationStatus
    created_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "structured_content", MappingProxyType(dict(self.structured_content)))


@dataclass(frozen=True, slots=True)
class Memory:
    tenant_id: UUID
    memory_id: UUID
    memory_type: MemoryType
    status: MemoryStatus
    scope: MemoryScope
    owner_user_id: UUID
    current_version_id: UUID
    revision: int
    created_at: datetime
    updated_at: datetime
    disabled_at: datetime | None = None

    @classmethod
    def create(
        cls,
        *,
        tenant_id: UUID,
        memory_id: UUID,
        version_id: UUID,
        memory_type: MemoryType,
        scope: MemoryScope,
        owner_user_id: UUID,
        content: str,
        now: datetime,
        status: MemoryStatus = MemoryStatus.ACTIVE,
        confidence: float = 1.0,
        utility: float = 1.0,
        authority_level: AuthorityLevel = AuthorityLevel.USER_CONFIRMED,
        verification_status: VerificationStatus = VerificationStatus.VERIFIED,
    ) -> tuple["Memory", MemoryVersion]:
        version = MemoryVersion(
            tenant_id=tenant_id,
            version_id=version_id,
            memory_id=memory_id,
            version_number=1,
            content=content,
            structured_content={},
            confidence=confidence,
            utility=utility,
            authority_level=authority_level,
            verification_status=verification_status,
            created_at=now,
        )
        memory = cls(
            tenant_id=tenant_id,
            memory_id=memory_id,
            memory_type=memory_type,
            status=status,
            scope=scope,
            owner_user_id=owner_user_id,
            current_version_id=version_id,
            revision=1,
            created_at=now,
            updated_at=now,
        )
        return memory, version

    def add_version(
        self,
        *,
        version_id: UUID,
        content: str,
        expected_revision: int,
        now: datetime,
    ) -> tuple["Memory", MemoryVersion]:
        if expected_revision != self.revision:
            raise RevisionConflict(
                f"expected revision {expected_revision}, current revision {self.revision}"
            )
        if self.status is not MemoryStatus.ACTIVE:
            raise InvalidStatusTransition(f"cannot version {self.status.value} memory")

        next_revision = self.revision + 1
        version = MemoryVersion(
            tenant_id=self.tenant_id,
            version_id=version_id,
            memory_id=self.memory_id,
            version_number=next_revision,
            content=content,
            structured_content={},
            confidence=1.0,
            utility=1.0,
            authority_level=AuthorityLevel.USER_CONFIRMED,
            verification_status=VerificationStatus.VERIFIED,
            created_at=now,
        )
        return (
            replace(
                self,
                current_version_id=version_id,
                revision=next_revision,
                updated_at=now,
            ),
            version,
        )

    def disable(self, status: MemoryStatus, now: datetime) -> "Memory":
        allowed = {
            MemoryStatus.SUPERSEDED,
            MemoryStatus.INVALIDATED,
            MemoryStatus.ARCHIVED,
            MemoryStatus.DELETED,
        }
        if self.status is MemoryStatus.DELETED:
            raise InvalidStatusTransition("deleted memory is terminal")
        if status not in allowed:
            raise InvalidStatusTransition(f"cannot disable memory with status {status.value}")
        return replace(
            self,
            status=status,
            revision=self.revision + 1,
            updated_at=now,
            disabled_at=now,
        )
