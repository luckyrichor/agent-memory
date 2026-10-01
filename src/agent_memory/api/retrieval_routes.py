from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException

from agent_memory.api.schemas import SearchHit, SearchRequest, SearchResponse
from agent_memory.application.retrieval import MemoryRetriever, RetrievalQuery
from agent_memory.config import Settings
from agent_memory.domain.errors import MemoryScopeForbidden
from agent_memory.domain.principal import RequestPrincipal
from agent_memory.infrastructure.embedding import HTTPEmbeddingProvider


def create_retrieval_router(
    principal_dependency: Callable[..., Awaitable[RequestPrincipal]],
    service_dependency: Callable[..., AsyncIterator[MemoryRetriever]],
    settings: Settings,
) -> APIRouter:
    router = APIRouter(prefix="/v1")

    @router.post("/memories/search", response_model=SearchResponse)
    async def search(body: SearchRequest,
                     principal: Annotated[RequestPrincipal, Depends(principal_dependency)],
                     service: Annotated[MemoryRetriever, Depends(service_dependency)],
                     ) -> SearchResponse:
        if "memory:read" not in principal.permissions:
            raise MemoryScopeForbidden("memory:read")
        if body.workspace_id and not principal.can_access_workspace(body.workspace_id):
            raise MemoryScopeForbidden(body.workspace_id)
        vector, model = body.vector, body.model
        vector_status = "caller_vector" if vector is not None else "not_configured"
        if vector is None and settings.embedding_endpoint and settings.embedding_model:
            async with httpx.AsyncClient(timeout=5) as client:
                provider = HTTPEmbeddingProvider(client, endpoint=settings.embedding_endpoint,
                    model=settings.embedding_model, token=settings.embedding_token.get_secret_value())
                try:
                    vector, model = await provider.embed(body.query), provider.model
                    RetrievalQuery(body.query, tuple(vector), model)
                    vector_status = "provider"
                except (httpx.HTTPError, ValueError, KeyError, TypeError, IndexError):
                    vector, model = None, None
                    vector_status = "degraded"
        try:
            query = RetrievalQuery(body.query, tuple(vector) if vector is not None else None,
                                   model, body.memory_type, body.workspace_id,
                                   body.limit, body.offset)
        except ValueError as error:
            raise HTTPException(422, "invalid query vector or pagination") from error
        page = await service.search(query, principal)
        return SearchResponse(items=[SearchHit(memory_id=hit.memory_id, version_id=hit.version_id,
            content=hit.content, score=hit.score, ranks=hit.ranks, raw_scores=hit.raw_scores)
            for hit in page.items], channel_counts=page.channel_counts,
            vector_status=vector_status, limit=query.limit, offset=query.offset,
            next_offset=page.next_offset)
    return router
