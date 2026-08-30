from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import Enum
from types import MappingProxyType
from uuid import UUID

from agent_memory.domain.errors import LeaseLost, LeaseUnavailable


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    RETRY_WAIT = "retry_wait"
    SUCCEEDED = "succeeded"
    DEAD = "dead"


@dataclass(frozen=True, slots=True)
class Job:
    tenant_id: UUID
    job_id: UUID
    job_type: str
    idempotency_key: str
    payload: Mapping[str, object]
    status: JobStatus
    attempts: int
    max_attempts: int
    available_at: datetime
    leased_until: datetime | None
    lease_owner: str | None
    last_error_code: str | None
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))

    def claim(self, worker_id: str, now: datetime, lease_duration: timedelta) -> "Job":
        eligible = (
            self.status in {JobStatus.PENDING, JobStatus.RETRY_WAIT}
            and self.available_at <= now
        ) or (
            self.status is JobStatus.RUNNING
            and self.leased_until is not None
            and self.leased_until <= now
        )
        if not eligible:
            raise LeaseUnavailable(str(self.job_id))
        return replace(
            self,
            status=JobStatus.RUNNING,
            attempts=self.attempts + 1,
            leased_until=now + lease_duration,
            lease_owner=worker_id,
            updated_at=now,
        )

    def renew(self, worker_id: str, now: datetime, lease_duration: timedelta) -> "Job":
        self._require_lease(worker_id, now)
        return replace(self, leased_until=now + lease_duration, updated_at=now)

    def succeed(self, worker_id: str, now: datetime) -> "Job":
        self._require_lease(worker_id, now)
        return replace(
            self,
            status=JobStatus.SUCCEEDED,
            leased_until=None,
            lease_owner=None,
            last_error_code=None,
            updated_at=now,
        )

    def fail(
        self,
        worker_id: str,
        now: datetime,
        error_code: str,
        *,
        retryable: bool,
    ) -> "Job":
        self._require_lease(worker_id, now)
        dead = not retryable or self.attempts >= self.max_attempts
        return replace(
            self,
            status=JobStatus.DEAD if dead else JobStatus.RETRY_WAIT,
            available_at=(
                now if dead else now + timedelta(seconds=min(2**self.attempts, 300))
            ),
            leased_until=None,
            lease_owner=None,
            last_error_code=error_code,
            updated_at=now,
        )

    def _require_lease(self, worker_id: str, now: datetime) -> None:
        if (
            self.status is not JobStatus.RUNNING
            or self.lease_owner != worker_id
            or self.leased_until is None
            or self.leased_until <= now
        ):
            raise LeaseLost(str(self.job_id))
