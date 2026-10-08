from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

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
    reason: str = Field(min_length=1, max_length=512)


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

    reason: str | None = None


class VersionListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[VersionResponse]
    limit: int = 20
    offset: int = 0
    next_offset: int | None = None


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    query: str = Field(min_length=1, max_length=2000)
    vector: list[float] | None = Field(default=None, min_length=1024, max_length=1024)
    model: str | None = Field(default=None, min_length=1, max_length=255)
    memory_type: MemoryType | None = None
    workspace_id: str | None = Field(default=None, min_length=1, max_length=512)
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=2900)


class SearchHit(BaseModel):
    memory_id: UUID
    version_id: UUID
    content: str
    score: float
    ranks: dict[str, int]
    raw_scores: dict[str, float]


class SearchResponse(BaseModel):
    fusion: str = "RRF(k=60;lexical=1;vector=1;structured=0.25)"
    items: list[SearchHit]
    channel_counts: dict[str, int]
    vector_status: str
    limit: int
    offset: int
    next_offset: int | None


class DeletionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    memory_id: UUID
    expected_revision: int


class DeletionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    memory_id: UUID
    status: str
    retrieval_disabled: bool


class SupersedeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int
    successor_id: UUID


class LifecycleResponse(BaseModel):
    memory_id: UUID
    status: MemoryStatus
    revision: int
    successor_id: UUID | None = None


class LifecycleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int
