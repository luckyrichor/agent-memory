from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

MemoryTypeName = Literal["episodic", "semantic", "procedural"]
ScopeKindName = Literal["tenant", "workspace", "user_global", "user_workspace"]


class FoundationCase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str
    tenant_id: UUID
    workspace_id: str
    expected_memory_type: MemoryTypeName
    expected_scope_kind: ScopeKindName
    expected_content: str


class FoundationActual(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_id: UUID
    memory_type: MemoryTypeName
    scope_kind: ScopeKindName
    content: str
    status: Literal["active", "needs_review", "rejected"]


class FoundationScore(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    passed: bool
    reasons: tuple[str, ...]
