"""Async HTTP client; authentication remains with the host application."""

from collections.abc import AsyncIterator
from uuid import UUID

import httpx

from agent_memory.api.event_schemas import EventBatchRequest, EventBatchResponse
from agent_memory.api.schemas import (
    DeletionResponse,
    LifecycleResponse,
    MemoryDetailResponse,
    MemoryResponse,
    SearchHit,
    SearchRequest,
    SearchResponse,
    VersionListResponse,
    VersionResponse,
)
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

    async def _request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, object] | None = None,
        key: str | None = None,
    ) -> object:
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

    async def remember(
        self, content: str, memory_type: MemoryType, scope: MemoryScope, *, idempotency_key: str
    ) -> MemoryResponse:
        return MemoryResponse.model_validate(
            await self._request(
                "POST",
                "/v1/memories",
                body={
                    "content": content,
                    "memory_type": memory_type.value,
                    "scope": {
                        "kind": scope.kind.value,
                        "workspace_id": scope.workspace_id,
                        "subject_user_id": str(scope.subject_user_id)
                        if scope.subject_user_id
                        else None,
                    },
                },
                key=idempotency_key,
            )
        )

    async def get(self, memory_id: UUID) -> MemoryDetailResponse:
        return MemoryDetailResponse.model_validate(
            await self._request("GET", f"/v1/memories/{memory_id}")
        )

    async def search(self, query: SearchRequest) -> SearchResponse:
        return SearchResponse.model_validate(
            await self._request("POST", "/v1/memories/search", body=query.model_dump(mode="json"))
        )

    async def correct(
        self,
        memory_id: UUID,
        *,
        expected_revision: int,
        content: str,
        reason: str = "user_correction",
    ) -> MemoryResponse:
        return MemoryResponse.model_validate(
            await self._request(
                "POST",
                f"/v1/memories/{memory_id}/versions",
                body={
                    "expected_revision": expected_revision,
                    "content": content,
                    "reason": reason,
                },
            )
        )

    async def delete(
        self, memory_id: UUID, *, expected_revision: int, idempotency_key: str
    ) -> DeletionResponse:
        return DeletionResponse.model_validate(
            await self._request(
                "POST",
                "/v1/deletion-requests",
                body={"memory_id": str(memory_id), "expected_revision": expected_revision},
                key=idempotency_key,
            )
        )

    async def archive(self, memory_id: UUID, *, expected_revision: int) -> MemoryResponse:
        return await self._disable(memory_id, expected_revision, "archive")

    async def supersede(
        self, memory_id: UUID, *, expected_revision: int, successor_id: UUID
    ) -> MemoryResponse:
        return MemoryResponse.model_validate(
            await self._request(
                "POST",
                f"/v1/memories/{memory_id}/supersede",
                body={"expected_revision": expected_revision, "successor_id": str(successor_id)},
            )
        )

    async def lifecycle(self, memory_id: UUID) -> LifecycleResponse:
        return LifecycleResponse.model_validate(
            await self._request("GET", f"/v1/memories/{memory_id}/lifecycle")
        )

    async def invalidate(self, memory_id: UUID, *, expected_revision: int) -> MemoryResponse:
        return await self._disable(memory_id, expected_revision, "invalidate")

    async def restore(self, memory_id: UUID, *, expected_revision: int) -> MemoryResponse:
        return await self._disable(memory_id, expected_revision, "restore")

    async def ingest_events(self, events: EventBatchRequest) -> EventBatchResponse:
        return EventBatchResponse.model_validate(
            await self._request("POST", "/v1/events:batch", body=events.model_dump(mode="json"))
        )

    async def versions(
        self, memory_id: UUID, *, limit: int = 20, offset: int = 0
    ) -> VersionListResponse:
        if not 1 <= limit <= 100 or offset < 0:
            raise ValueError("invalid pagination")
        return VersionListResponse.model_validate(
            await self._request(
                "GET", f"/v1/memories/{memory_id}/versions?limit={limit}&offset={offset}"
            )
        )

    async def iter_versions(
        self, memory_id: UUID, *, page_size: int = 100
    ) -> AsyncIterator[VersionResponse]:
        offset = 0
        while True:
            page = await self.versions(memory_id, limit=page_size, offset=offset)
            for item in page.items:
                yield item
            if page.next_offset is None:
                break
            if page.next_offset <= offset:
                raise ValueError("non-progressing pagination")
            offset = page.next_offset

    async def iter_search(self, query: SearchRequest) -> AsyncIterator[SearchHit]:
        while True:
            page = await self.search(query)
            for item in page.items:
                yield item
            if page.next_offset is None:
                break
            if page.next_offset <= query.offset:
                raise ValueError("non-progressing pagination")
            query = query.model_copy(update={"offset": page.next_offset})

    async def _disable(self, memory_id: UUID, revision: int, action: str) -> MemoryResponse:
        return MemoryResponse.model_validate(
            await self._request(
                "POST", f"/v1/memories/{memory_id}/{action}", body={"expected_revision": revision}
            )
        )
