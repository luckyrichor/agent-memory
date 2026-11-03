from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import asdict
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException

from agent_memory.api.schemas import (
    ContextRequest,
    ContextResponse,
    EvidenceRefOut,
    SearchHit,
    SearchRequest,
    SearchResponse,
)
from agent_memory.application.context_builder import MemoryContextBuilder
from agent_memory.application.context_scoring import ContextScoring
from agent_memory.application.retrieval import (
    MemoryRetriever,
    RetrievalPage,
    RetrievalQuery,
)
from agent_memory.config import Settings
from agent_memory.domain.enums import MemoryType
from agent_memory.domain.errors import MemoryScopeForbidden
from agent_memory.domain.principal import RequestPrincipal
from agent_memory.infrastructure.query_vectors import QueryVectors
from agent_memory.observability import record_operation


def create_retrieval_router(
    principal_dependency: Callable[..., Awaitable[RequestPrincipal]],
    service_dependency: Callable[..., AsyncIterator[MemoryRetriever]],
    settings: Settings,
    vectors: QueryVectors,
) -> APIRouter:
    router = APIRouter(prefix="/v1")

    def context_scoring() -> ContextScoring:
        """E3 weights from settings. Kept here so config stays free of application imports."""
        return ContextScoring(
            relevance_weight=settings.context_relevance_weight,
            recency_weight=settings.context_recency_weight,
            authority_weight=settings.context_authority_weight,
            min_relevance=settings.context_min_relevance,
            half_life_days={
                MemoryType.EPISODIC: settings.context_half_life_episodic_days,
                MemoryType.SEMANTIC: settings.context_half_life_semantic_days,
                MemoryType.PROCEDURAL: settings.context_half_life_procedural_days,
            },
        )

    async def run_search(
        body: SearchRequest,
        principal: RequestPrincipal,
        service: MemoryRetriever,
    ) -> tuple[RetrievalPage, RetrievalQuery, str]:
        """The one place that turns a request into a page, shared by search and context.

        Context used to rebuild hits out of ``SearchHit`` models, which dropped the metadata E3
        scores on. Going through the real page keeps the two endpoints honest about the same data.
        """
        if "memory:read" not in principal.permissions:
            raise MemoryScopeForbidden("memory:read")
        if body.workspace_id and not principal.can_access_workspace(body.workspace_id):
            raise MemoryScopeForbidden(body.workspace_id)
        vector, model = body.vector, body.model
        vector_status = "caller_vector" if vector is not None else "not_configured"
        if vector is None and settings.embedding_endpoint and settings.embedding_model:
            try:
                vector, vector_status = await vectors.embed(principal.tenant_id, body.query)
                model = settings.embedding_model
            except (httpx.HTTPError, TimeoutError, ValueError, KeyError, TypeError, IndexError):
                vector, model = None, None
                vector_status = "degraded"
        record_operation(
            action="memory.query_embedding",
            decision=vector_status,
            reason_code="QUERY_VECTOR_" + vector_status.upper(),
        )
        try:
            query = RetrievalQuery(
                body.query,
                tuple(vector) if vector is not None else None,
                model,
                body.memory_type,
                body.workspace_id,
                body.limit,
                body.offset,
            )
        except ValueError as error:
            raise HTTPException(422, "invalid query vector or pagination") from error
        page = await service.search(query, principal)
        return page, query, vector_status

    @router.post("/memories/search", response_model=SearchResponse)
    async def search(
        body: SearchRequest,
        principal: Annotated[RequestPrincipal, Depends(principal_dependency)],
        service: Annotated[MemoryRetriever, Depends(service_dependency)],
    ) -> SearchResponse:
        page, query, vector_status = await run_search(body, principal, service)
        return SearchResponse(
            items=[
                SearchHit(
                    memory_id=hit.memory_id,
                    version_id=hit.version_id,
                    content=hit.content,
                    score=hit.score,
                    ranks=hit.ranks,
                    raw_scores=hit.raw_scores,
                    evidence=[EvidenceRefOut(**asdict(ref)) for ref in hit.evidence],
                    evidence_total=hit.evidence_total,
                )
                for hit in page.items
            ],
            channel_counts=page.channel_counts,
            vector_status=vector_status,
            limit=query.limit,
            offset=query.offset,
            next_offset=page.next_offset,
        )

    @router.post("/memories/context", response_model=ContextResponse)
    async def context(
        body: ContextRequest,
        principal: Annotated[RequestPrincipal, Depends(principal_dependency)],
        service: Annotated[MemoryRetriever, Depends(service_dependency)],
    ) -> ContextResponse:
        page, _, _ = await run_search(body, principal, service)
        packet = MemoryContextBuilder(
            scoring=context_scoring(),
            conflict_similarity=settings.context_conflict_similarity,
        ).build(page.items, body.token_budget)
        return ContextResponse.model_validate(asdict(packet))

    return router
