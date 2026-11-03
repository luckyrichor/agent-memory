"""Map database/pool failures to a stable HTTP contract (B4 pool exhaustion, D2 storage errors).

Rules: never put exception text (it can contain SQL parameters or content) in a response or log;
only the SQLSTATE class decides. Overload and unavailability are 503 with ``Retry-After`` and
``retryable: true`` so clients back off instead of hammering a saturated service.
"""
from dataclasses import dataclass

from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.exc import TimeoutError as PoolTimeout


@dataclass(frozen=True, slots=True)
class InfrastructureFailure:
    status_code: int
    code: str
    message: str
    retryable: bool
    reason_code: str
    retry_after: int | None = None


_STORAGE = {"53100", "53000", "53200", "53400"}  # disk full, insufficient resources, OOM, limit
_UNAVAILABLE = {"53300", "57P01", "57P02", "57P03", "08000", "08001", "08003", "08004", "08006"}


def sqlstate(error: BaseException) -> str | None:
    original = getattr(error, "orig", error)
    value = getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)
    return value if isinstance(value, str) else None


def classify_infrastructure_error(error: SQLAlchemyError) -> InfrastructureFailure:
    if isinstance(error, PoolTimeout):
        return InfrastructureFailure(
            503, "SERVICE_OVERLOADED", "The service is busy; retry shortly.", True,
            "DB_POOL_EXHAUSTED", retry_after=1,
        )
    state = sqlstate(error)
    if state in _STORAGE:
        return InfrastructureFailure(
            503, "STORAGE_UNAVAILABLE", "Storage is temporarily unavailable.", True,
            "DB_STORAGE_LIMIT", retry_after=30,
        )
    if state == "57014":  # query_canceled: statement_timeout
        return InfrastructureFailure(
            504, "DATABASE_TIMEOUT", "The request took too long to complete.", True,
            "DB_STATEMENT_TIMEOUT", retry_after=5,
        )
    if state in _UNAVAILABLE or (
        isinstance(error, OperationalError)
        and (state is None or error.connection_invalidated)
    ):
        return InfrastructureFailure(
            503, "DATABASE_UNAVAILABLE", "The database is temporarily unavailable.", True,
            "DB_UNAVAILABLE", retry_after=5,
        )
    return InfrastructureFailure(
        500, "INTERNAL_ERROR", "The request could not be completed.", False, "DB_ERROR"
    )
