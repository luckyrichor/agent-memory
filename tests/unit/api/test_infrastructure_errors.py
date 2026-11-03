import pytest
from sqlalchemy.exc import DBAPIError, IntegrityError, OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeout

from agent_memory.api.infrastructure_errors import classify_infrastructure_error


class FakePgError(Exception):
    def __init__(self, state: str | None) -> None:
        super().__init__("secret statement text must never be echoed")
        self.sqlstate = state


def wrap(cls: type[DBAPIError], state: str | None) -> DBAPIError:
    return cls("SELECT secret", {"p": "content"}, FakePgError(state))


def test_pool_exhaustion_is_a_fast_503_with_retry_after() -> None:
    failure = classify_infrastructure_error(PoolTimeout("QueuePool limit reached"))
    assert (failure.status_code, failure.code, failure.retryable) == (
        503, "SERVICE_OVERLOADED", True
    )
    assert failure.retry_after == 1


@pytest.mark.parametrize("state", ["53100", "53200", "53000", "53400"])
def test_disk_full_and_resource_limits_are_storage_unavailable(state: str) -> None:
    failure = classify_infrastructure_error(wrap(OperationalError, state))
    assert (failure.status_code, failure.code) == (503, "STORAGE_UNAVAILABLE")
    assert failure.reason_code == "DB_STORAGE_LIMIT" and failure.retry_after == 30


def test_statement_timeout_is_a_504() -> None:
    failure = classify_infrastructure_error(wrap(OperationalError, "57014"))
    assert (failure.status_code, failure.code) == (504, "DATABASE_TIMEOUT")


@pytest.mark.parametrize("state", ["53300", "57P01", "08006", None])
def test_connection_level_failures_are_database_unavailable(state: str | None) -> None:
    failure = classify_infrastructure_error(wrap(OperationalError, state))
    assert (failure.status_code, failure.code) == (503, "DATABASE_UNAVAILABLE")


def test_unrecognized_errors_stay_500_and_never_retryable() -> None:
    failure = classify_infrastructure_error(wrap(IntegrityError, "23505"))
    assert (failure.status_code, failure.code, failure.retryable) == (500, "INTERNAL_ERROR", False)


def test_messages_never_contain_exception_text() -> None:
    for error in (
        PoolTimeout("secret"), wrap(OperationalError, "53100"), wrap(IntegrityError, "23505"),
    ):
        failure = classify_infrastructure_error(error)
        assert "secret" not in failure.message and "content" not in failure.message
