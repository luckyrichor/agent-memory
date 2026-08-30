from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, status

from agent_memory.api.schemas import (
    CorrectMemoryRequest,
    DeletionRequest,
    DeletionResponse,
    MemoryDetailResponse,
    MemoryResponse,
    RememberRequest,
    VersionListResponse,
    VersionResponse,
)
from agent_memory.application.commands import (
    CorrectMemoryCommand,
    DisableMemoryCommand,
    RememberMemoryCommand,
)
from agent_memory.application.explicit_memory import ExplicitMemoryService
from agent_memory.domain.enums import MemoryStatus
from agent_memory.domain.models import MemoryScope
from agent_memory.domain.principal import RequestPrincipal


def create_router(
    principal_dependency: Callable[..., Awaitable[RequestPrincipal]],
    service_dependency: Callable[..., AsyncIterator[ExplicitMemoryService]],
) -> APIRouter:
    router = APIRouter(prefix="/v1")

    @router.post(
        "/memories",
        response_model=MemoryResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def remember(
        body: RememberRequest,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
        principal: Annotated[RequestPrincipal, Depends(principal_dependency)],
        service: Annotated[
            ExplicitMemoryService,
            Depends(service_dependency),
        ],
    ) -> MemoryResponse:
        result = await service.remember(
            RememberMemoryCommand(
                content=body.content,
                memory_type=body.memory_type,
                scope=MemoryScope(
                    body.scope.kind,
                    body.scope.workspace_id,
                    body.scope.subject_user_id,
                ),
                idempotency_key=idempotency_key,
            ),
            principal,
        )
        return MemoryResponse(
            tenant_id=principal.tenant_id,
            memory_id=result.memory_id,
            version_id=result.version_id,
            revision=result.revision,
            status=result.status,
        )

    @router.get("/memories/{memory_id}", response_model=MemoryDetailResponse)
    async def get_memory(
        memory_id: UUID,
        principal: Annotated[RequestPrincipal, Depends(principal_dependency)],
        service: Annotated[
            ExplicitMemoryService,
            Depends(service_dependency),
        ],
    ) -> MemoryDetailResponse:
        record = await service.get_active(memory_id, principal)
        return MemoryDetailResponse(
            tenant_id=principal.tenant_id,
            memory_id=record.memory.memory_id,
            memory_type=record.memory.memory_type,
            status=record.memory.status,
            revision=record.memory.revision,
            content=record.current_version.content,
        )

    @router.get(
        "/memories/{memory_id}/versions",
        response_model=VersionListResponse,
    )
    async def get_versions(
        memory_id: UUID,
        principal: Annotated[RequestPrincipal, Depends(principal_dependency)],
        service: Annotated[
            ExplicitMemoryService,
            Depends(service_dependency),
        ],
    ) -> VersionListResponse:
        record = await service.get_active(memory_id, principal)
        return VersionListResponse(
            items=[
                VersionResponse(
                    version_id=version.version_id,
                    version_number=version.version_number,
                    content=version.content,
                )
                for version in record.versions
            ]
        )

    @router.post(
        "/memories/{memory_id}/versions",
        response_model=MemoryResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def correct_memory(
        memory_id: UUID,
        body: CorrectMemoryRequest,
        principal: Annotated[RequestPrincipal, Depends(principal_dependency)],
        service: Annotated[
            ExplicitMemoryService,
            Depends(service_dependency),
        ],
    ) -> MemoryResponse:
        result = await service.correct(
            CorrectMemoryCommand(
                memory_id=memory_id,
                expected_revision=body.expected_revision,
                content=body.content,
                reason=body.reason,
            ),
            principal,
        )
        return MemoryResponse(
            tenant_id=principal.tenant_id,
            memory_id=result.memory_id,
            version_id=result.version_id,
            revision=result.revision,
            status=result.status,
        )

    @router.post(
        "/deletion-requests",
        response_model=DeletionResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def delete_memory(
        body: DeletionRequest,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
        principal: Annotated[RequestPrincipal, Depends(principal_dependency)],
        service: Annotated[
            ExplicitMemoryService,
            Depends(service_dependency),
        ],
    ) -> DeletionResponse:
        del idempotency_key
        result = await service.disable(
            DisableMemoryCommand(
                memory_id=body.memory_id,
                expected_revision=body.expected_revision,
                status=MemoryStatus.DELETED,
            ),
            principal,
        )
        return DeletionResponse(
            memory_id=result.memory_id,
            status="pending_physical_cleanup",
            retrieval_disabled=True,
        )

    return router
