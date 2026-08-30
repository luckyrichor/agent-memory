from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse

from agent_memory.api.auth import JwtPrincipalResolver
from agent_memory.api.errors import AuthenticationRequired
from agent_memory.api.event_routes import create_event_router
from agent_memory.api.routes import create_router
from agent_memory.application.event_ingestion import EventIngestionService
from agent_memory.application.explicit_memory import ExplicitMemoryService
from agent_memory.config import Settings
from agent_memory.domain.errors import (
    EventIdempotencyConflict,
    EventScopeForbidden,
    EventSequenceConflict,
    IdempotencyConflict,
    InvalidEvent,
    MemoryNotFound,
    MemoryScopeForbidden,
    RevisionConflict,
)
from agent_memory.domain.principal import RequestPrincipal
from agent_memory.infrastructure.db import (
    create_engine,
    create_session_factory,
    session_for_principal,
)
from agent_memory.infrastructure.event_repositories import PostgresEventIngestionRepository
from agent_memory.infrastructure.repositories import (
    PostgresAuditSink,
    PostgresIdempotencyRepository,
    PostgresMemoryRepository,
)


def create_app(settings: Settings) -> FastAPI:
    app = FastAPI(title="Agent Memory", version="1.0.0")
    engine = create_engine(settings.database_url)
    sessions = create_session_factory(engine)
    resolver = JwtPrincipalResolver(settings)
    app.state.engine = engine

    async def service_dependency(
        principal: Annotated[RequestPrincipal, Depends(resolver)],
    ) -> AsyncIterator[ExplicitMemoryService]:
        async with session_for_principal(sessions, principal) as session:
            yield ExplicitMemoryService(
                memory_repository=PostgresMemoryRepository(session),
                idempotency_repository=PostgresIdempotencyRepository(
                    session,
                    now=lambda: datetime.now(UTC),
                ),
                audit_sink=PostgresAuditSink(
                    session,
                    new_id=uuid4,
                    now=lambda: datetime.now(UTC),
                ),
                new_id=uuid4,
                now=lambda: datetime.now(UTC),
            )

    async def event_service_dependency(
        principal: Annotated[RequestPrincipal, Depends(resolver)],
    ) -> AsyncIterator[EventIngestionService]:
        async with session_for_principal(sessions, principal) as session:
            yield EventIngestionService(
                PostgresEventIngestionRepository(
                    session,
                    new_id=uuid4,
                    now=lambda: datetime.now(UTC),
                )
            )

    @app.exception_handler(AuthenticationRequired)
    async def authentication_error(
        request: Request,
        error: AuthenticationRequired,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=401,
            content={
                "error": {
                    "code": "AUTHENTICATION_REQUIRED",
                    "message": "A valid bearer token is required.",
                    "retryable": False,
                    "request_id": request.headers.get("X-Request-Id", "unavailable"),
                }
            },
        )

    def domain_error_response(request: Request, code: str, message: str, status_code: int) -> JSONResponse:
        return JSONResponse(
            status_code=status_code,
            content={
                "error": {
                    "code": code,
                    "message": message,
                    "retryable": False,
                    "request_id": request.headers.get("X-Request-Id", "unavailable"),
                }
            },
        )

    @app.exception_handler(MemoryNotFound)
    async def memory_not_found(request: Request, error: MemoryNotFound) -> JSONResponse:
        return domain_error_response(request, "MEMORY_NOT_FOUND", "Memory was not found.", 404)

    @app.exception_handler(MemoryScopeForbidden)
    async def memory_forbidden(request: Request, error: MemoryScopeForbidden) -> JSONResponse:
        return domain_error_response(
            request,
            "MEMORY_SCOPE_FORBIDDEN",
            "The caller cannot access this memory scope.",
            403,
        )

    @app.exception_handler(RevisionConflict)
    async def revision_conflict(request: Request, error: RevisionConflict) -> JSONResponse:
        return domain_error_response(
            request,
            "MEMORY_VERSION_CONFLICT",
            "The memory revision has changed.",
            409,
        )

    @app.exception_handler(IdempotencyConflict)
    async def idempotency_conflict(request: Request, error: IdempotencyConflict) -> JSONResponse:
        return domain_error_response(
            request,
            "IDEMPOTENCY_CONFLICT",
            "The idempotency key was reused with different input.",
            409,
        )

    @app.exception_handler(EventScopeForbidden)
    async def event_scope_forbidden(
        request: Request,
        error: EventScopeForbidden,
    ) -> JSONResponse:
        return domain_error_response(
            request,
            "EVENT_SCOPE_FORBIDDEN",
            "The caller cannot access this event scope.",
            403,
        )

    @app.exception_handler(EventIdempotencyConflict)
    async def event_idempotency_conflict(
        request: Request,
        error: EventIdempotencyConflict,
    ) -> JSONResponse:
        return domain_error_response(
            request,
            "EVENT_IDEMPOTENCY_CONFLICT",
            "The event idempotency key was reused with different input.",
            409,
        )

    @app.exception_handler(EventSequenceConflict)
    async def event_sequence_conflict(
        request: Request,
        error: EventSequenceConflict,
    ) -> JSONResponse:
        return domain_error_response(
            request,
            "EVENT_SEQUENCE_CONFLICT",
            "The session sequence number is already occupied.",
            409,
        )

    @app.exception_handler(InvalidEvent)
    async def invalid_event(request: Request, error: InvalidEvent) -> JSONResponse:
        return domain_error_response(
            request,
            "EVENT_BATCH_INVALID",
            "The event batch is invalid.",
            422,
        )

    app.include_router(create_router(resolver, service_dependency))
    app.include_router(create_event_router(resolver, event_service_dependency))
    return app


def create_app_from_env() -> FastAPI:
    """Build the ASGI application from MEMORY_* environment variables."""
    return create_app(Settings())
