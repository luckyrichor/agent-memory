from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class RequestPrincipal:
    tenant_id: UUID
    user_id: UUID
    roles: frozenset[str]
    permissions: frozenset[str]
    allowed_workspace_ids: frozenset[str]

    def can_access_workspace(self, workspace_id: str | None) -> bool:
        return workspace_id is not None and workspace_id in self.allowed_workspace_ids
