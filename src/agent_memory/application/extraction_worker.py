from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal, Protocol
from uuid import UUID

from agent_memory.application.extraction import MemoryExtractor
from agent_memory.domain.errors import InvalidEvent, LeaseLost, RetryableExtractionError
from agent_memory.domain.events import Event, MemoryCandidate
from agent_memory.domain.jobs import Job, JobStatus


@dataclass(frozen=True, slots=True)
class WorkerResult:
    job_id: UUID | None
    outcome: Literal["no_job", "succeeded", "retry_wait", "dead", "lease_lost"]
    reason_code: str


class ExtractionBackend(Protocol):
    async def claim(
        self,
        tenant_id: UUID,
        worker_id: str,
        now: datetime,
        lease_duration: timedelta,
    ) -> Job | None: ...

    async def load_event(self, tenant_id: UUID, event_id: UUID) -> Event: ...

    async def commit_candidates(
        self,
        tenant_id: UUID,
        job: Job,
        worker_id: str,
        event: Event,
        candidates: tuple[MemoryCandidate, ...],
        now: datetime,
    ) -> None: ...

    async def fail_job(
        self,
        tenant_id: UUID,
        job_id: UUID,
        worker_id: str,
        now: datetime,
        error_code: str,
        *,
        retryable: bool,
    ) -> Job: ...


class ExtractionWorker:
    def __init__(
        self,
        backend: ExtractionBackend,
        extractor: MemoryExtractor,
        *,
        now: Callable[[], datetime],
        lease_duration: timedelta,
    ) -> None:
        self._backend = backend
        self._extractor = extractor
        self._now = now
        self._lease_duration = lease_duration

    async def run_once(self, tenant_id: UUID, worker_id: str) -> WorkerResult:
        job = await self._backend.claim(
            tenant_id,
            worker_id,
            self._now(),
            self._lease_duration,
        )
        if job is None:
            return WorkerResult(None, "no_job", "NO_JOB_AVAILABLE")
        try:
            event_id = UUID(str(job.payload["event_id"]))
            if job.payload.get("extractor_version") != self._extractor.version:
                raise InvalidEvent("extractor version mismatch")
            event = await self._backend.load_event(tenant_id, event_id)
            candidates = await self._extractor.extract(event)
            if any(candidate.scope != event.draft.scope for candidate in candidates):
                raise InvalidEvent("candidate scope expansion")
            await self._backend.commit_candidates(
                tenant_id,
                job,
                worker_id,
                event,
                candidates,
                self._now(),
            )
            return WorkerResult(job.job_id, "succeeded", "JOB_SUCCEEDED")
        except LeaseLost:
            return WorkerResult(job.job_id, "lease_lost", "LEASE_LOST")
        except (InvalidEvent, KeyError, TypeError, ValueError):
            await self._backend.fail_job(
                tenant_id,
                job.job_id,
                worker_id,
                self._now(),
                "INVALID_EVENT_FOR_EXTRACTION",
                retryable=False,
            )
            return WorkerResult(job.job_id, "dead", "INVALID_EVENT_FOR_EXTRACTION")
        except RetryableExtractionError:
            failed = await self._backend.fail_job(
                tenant_id,
                job.job_id,
                worker_id,
                self._now(),
                "EXTRACTION_FAILED",
                retryable=True,
            )
            outcome: Literal["retry_wait", "dead"] = (
                "dead" if failed.status is JobStatus.DEAD else "retry_wait"
            )
            return WorkerResult(job.job_id, outcome, "EXTRACTION_FAILED")
