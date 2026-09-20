"""Request-scoped correlation context.

Every log line and span carries the same ``request_id`` and ``tenant_id`` so a
single request can be followed across the API, the services and the workers
without threading a context object through every call signature.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from uuid import UUID

_request_id: ContextVar[str | None] = ContextVar("agent_memory_request_id", default=None)
_tenant_id: ContextVar[str | None] = ContextVar("agent_memory_tenant_id", default=None)


@contextmanager
def correlation(
    *,
    request_id: str | None = None,
    tenant_id: UUID | str | None = None,
) -> Iterator[None]:
    """Bind correlation identifiers for the duration of the block."""
    request_token = _request_id.set(request_id) if request_id is not None else None
    tenant_token = _tenant_id.set(str(tenant_id)) if tenant_id is not None else None
    try:
        yield
    finally:
        if tenant_token is not None:
            _tenant_id.reset(tenant_token)
        if request_token is not None:
            _request_id.reset(request_token)


def bind_tenant(tenant_id: UUID | str) -> None:
    """Attach the tenant to the current context once authentication resolves it."""
    _tenant_id.set(str(tenant_id))


def current_request_id() -> str | None:
    return _request_id.get()


def current_tenant_id() -> str | None:
    return _tenant_id.get()


def current_correlation() -> dict[str, str]:
    """Return the bound identifiers, omitting the ones that are not set."""
    values = {"request_id": current_request_id(), "tenant_id": current_tenant_id()}
    return {key: value for key, value in values.items() if value is not None}
