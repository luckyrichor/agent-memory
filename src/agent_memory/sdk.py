"""Async HTTP client; authentication remains with the host application."""
from uuid import UUID

import httpx

from agent_memory.api.schemas import DeletionResponse, MemoryDetailResponse, MemoryResponse
from agent_memory.domain.enums import MemoryType
from agent_memory.domain.models import MemoryScope


class MemoryAPIError(Exception):
    def __init__(self, status_code: int, code: str) -> None:
        self.status_code = status_code
        self.code = code
        super().__init__(f"Memory API {status_code}: {code}")


class MemoryClient:
    def __init__(self, client: httpx.AsyncClient, *, token: str) -> None:
        """Caller owns client lifetime, base URL and timeout; no automatic write retries."""
        self._client = client
        self._headers = {"Authorization": f"Bearer {token}"}

    async def _request(self, method: str, path: str, *, body: dict[str, object] | None = None,
                       key: str | None = None) -> object:
        headers = dict(self._headers)
        if key is not None:
            headers["Idempotency-Key"] = key
        response = await self._client.request(method, path, json=body, headers=headers)
        if response.is_error:
            code = "HTTP_ERROR"
            try:
                code = str(response.json()["error"]["code"])
            except (ValueError, KeyError, TypeError):
                pass
            raise MemoryAPIError(response.status_code, code)
        return response.json()

    async def remember(self, content: str, memory_type: MemoryType, scope: MemoryScope,
                       *, idempotency_key: str) -> MemoryResponse:
        return MemoryResponse.model_validate(await self._request("POST", "/v1/memories", body={
            "content": content, "memory_type": memory_type.value,
            "scope": {"kind": scope.kind.value, "workspace_id": scope.workspace_id,
                      "subject_user_id": str(scope.subject_user_id) if scope.subject_user_id else None},
        }, key=idempotency_key))

    async def get(self, memory_id: UUID) -> MemoryDetailResponse:
        return MemoryDetailResponse.model_validate(
            await self._request("GET", f"/v1/memories/{memory_id}"))

    async def correct(self, memory_id: UUID, *, expected_revision: int, content: str,
                      reason: str = "user_correction") -> MemoryResponse:
        return MemoryResponse.model_validate(await self._request(
            "POST", f"/v1/memories/{memory_id}/versions", body={
                "expected_revision": expected_revision, "content": content, "reason": reason,
            }))

    async def delete(self, memory_id: UUID, *, expected_revision: int,
                     idempotency_key: str) -> DeletionResponse:
        return DeletionResponse.model_validate(await self._request(
            "POST", "/v1/deletion-requests", body={"memory_id": str(memory_id),
                "expected_revision": expected_revision}, key=idempotency_key))

    async def archive(self, memory_id: UUID, *, expected_revision: int) -> MemoryResponse:
        return await self._disable(memory_id, expected_revision, "archive")

    async def supersede(self, memory_id: UUID, *, expected_revision: int) -> MemoryResponse:
        return await self._disable(memory_id, expected_revision, "supersede")

    async def _disable(self, memory_id: UUID, revision: int, action: str) -> MemoryResponse:
        return MemoryResponse.model_validate(await self._request(
            "POST", f"/v1/memories/{memory_id}/{action}", body={"expected_revision": revision}))
