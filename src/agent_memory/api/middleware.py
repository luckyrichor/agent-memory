"""Edge instrumentation: correlation id, root span, access log, metrics.

The middleware owns the outermost span of every request, so the service and
repository spans created further in appear as its children -- that tree is what
makes a write or read request traceable end to end.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from uuid import uuid4

from starlette.requests import Request
from starlette.responses import Response

from agent_memory.observability import annotate, correlation, get_logger, record_request, span

REQUEST_ID_HEADER = "X-Request-Id"

_logger = get_logger("agent_memory.api")

CallNext = Callable[[Request], Awaitable[Response]]


async def observe_request(request: Request, call_next: CallNext) -> Response:
    request_id = _request_id(request)
    request.state.request_id = request_id
    started = time.perf_counter()
    with correlation(request_id=request_id), span(
        f"http {request.method}",
        http_method=request.method,
        request_id=request_id,
    ) as http_span:
        response = await call_next(request)
        duration_ms = (time.perf_counter() - started) * 1000
        route = _route_template(request)
        tenant_id = getattr(request.state, "tenant_id", None)
        http_span.update_name(f"{request.method} {route}")
        annotate(route=route, http_status=response.status_code, duration_ms=round(duration_ms, 3))
        response.headers[REQUEST_ID_HEADER] = request_id
        record_request(
            route=route,
            http_method=request.method,
            http_status=response.status_code,
            duration_ms=duration_ms,
        )
        _logger.event(
            "http.request",
            request_id=request_id,
            tenant_id=tenant_id,
            route=route,
            http_method=request.method,
            http_status=response.status_code,
            duration_ms=round(duration_ms, 3),
        )
        return response


def _request_id(request: Request) -> str:
    """Honour an inbound correlation id, but never let it become a payload."""
    inbound = request.headers.get(REQUEST_ID_HEADER, "")
    if inbound and len(inbound) <= 64 and inbound.isascii() and inbound.isprintable():
        return inbound
    return str(uuid4())


def _route_template(request: Request) -> str:
    """The path template, not the concrete path: ids stay out of metric labels."""
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    return path if isinstance(path, str) else "unmatched"
