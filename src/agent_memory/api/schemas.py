from uuid import UUID

from pydantic import BaseModel, ConfigDict

from agent_memory.domain.enums import MemoryStatus, MemoryType, ScopeKind


class ScopeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: ScopeKind
    workspace_id: str | None = None
    subject_user_id: UUID | None = None


class RememberRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str
    memory_type: MemoryType
    scope: ScopeRequest


class MemoryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID
    memory_id: UUID
    version_id: UUID
    revision: int
    status: MemoryStatus


class CorrectMemoryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int
    content: str
    reason: str


class MemoryDetailResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID
    memory_id: UUID
    memory_type: MemoryType
    status: MemoryStatus
    revision: int
    content: str


class VersionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version_id: UUID
    version_number: int
    content: str


class VersionListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[VersionResponse]


class DeletionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    memory_id: UUID
    expected_revision: int


class DeletionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    memory_id: UUID
    status: str
    retrieval_disabled: bool
