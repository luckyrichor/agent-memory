from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Annotated

from fastapi import APIRouter, Depends, status

from agent_memory.api.event_schemas import (
    EventBatchRequest,
    EventBatchResponse,
    EventIngestionItemResponse,
)
from agent_memory.application.event_commands import IngestEventBatchCommand
from agent_memory.application.event_ingestion import EventIngestionService
from agent_memory.domain.events import EventDraft, EventType
from agent_memory.domain.models import MemoryScope
from agent_memory.domain.principal import RequestPrincipal


def create_event_router(
    principal_dependency: Callable[..., Awaitable[RequestPrincipal]],
    service_dependency: Callable[..., AsyncIterator[EventIngestionService]],
) -> APIRouter:
    router = APIRouter(prefix="/v1")

    @router.post(
        "/events:batch",
        response_model=EventBatchResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def ingest_events(
        body: EventBatchRequest,
        principal: Annotated[RequestPrincipal, Depends(principal_dependency)],
        service: Annotated[EventIngestionService, Depends(service_dependency)],
    ) -> EventBatchResponse:
        results = await service.ingest_batch(
            IngestEventBatchCommand(
                tuple(
                    EventDraft(
                        idempotency_key=item.idempotency_key,
                        session_id=item.session_id,
                        sequence_number=item.sequence_number,
                        event_type=EventType(item.event_type),
                        agent_id=item.agent_id,
                        occurred_at=item.occurred_at,
                        scope=MemoryScope(
                            item.scope.kind,
                            item.scope.workspace_id,
                            item.scope.subject_user_id,
                        ),
                        payload=item.payload.model_dump(exclude_none=True),
                    )
                    for item in body.events
                )
            ),
            principal,
        )
        return EventBatchResponse(
            items=[
                EventIngestionItemResponse(
                    event_id=result.event_id,
                    idempotency_key=result.idempotency_key,
                    disposition=result.disposition,
                )
                for result in results
            ]
        )

    return router
