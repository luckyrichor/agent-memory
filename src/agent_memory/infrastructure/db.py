from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from opentelemetry.trace import Span, StatusCode
from sqlalchemy import event, text
from sqlalchemy.engine import Connection, ExceptionContext
from sqlalchemy.engine.interfaces import ExecutionContext
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from agent_memory.domain.principal import RequestPrincipal
from agent_memory.observability import span
from agent_memory.observability.tracing import tracer


def create_engine(database_url: str) -> AsyncEngine:
    engine = create_async_engine(database_url, pool_pre_ping=True)

    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def before(
        conn: Connection,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: ExecutionContext,
        executemany: bool,
    ) -> None:
        verb = statement.lstrip().split(None, 1)[0].upper() if statement.strip() else "OTHER"
        if verb not in {"SELECT", "INSERT", "UPDATE", "DELETE", "SET", "BEGIN", "COMMIT"}:
            verb = "OTHER"
        conn.info["memory_statement_span"] = tracer().start_span("db." + verb.lower())

    @event.listens_for(engine.sync_engine, "after_cursor_execute")
    def after(
        conn: Connection,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: ExecutionContext,
        executemany: bool,
    ) -> None:
        current: Span | None = conn.info.pop("memory_statement_span", None)
        if current:
            current.end()

    @event.listens_for(engine.sync_engine, "handle_error")
    def failed(context: ExceptionContext) -> None:
        if context.connection is not None:
            current: Span | None = context.connection.info.pop("memory_statement_span", None)
            if current:
                current.set_status(StatusCode.ERROR)
                current.end()

    return engine


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def session_for_principal(
    session_factory: async_sessionmaker[AsyncSession],
    principal: RequestPrincipal,
) -> AsyncIterator[AsyncSession]:
    with span("db.session", tenant_id=principal.tenant_id):
        async with session_factory() as session, session.begin():
            await session.execute(
                text("SELECT set_config('app.current_tenant_id', :tenant_id, true)"),
                {"tenant_id": str(principal.tenant_id)},
            )
            yield session
