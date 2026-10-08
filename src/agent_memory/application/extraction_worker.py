from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Literal, Protocol
from uuid import UUID

from agent_memory.application.extraction import MemoryExtractor
from agent_memory.domain.errors import (
    ExtractorVersionMismatch,
    InvalidEvent,
    LeaseLost,
    RetryableExtractionError,
)
from agent_memory.domain.events import Event, MemoryCandidate
from agent_memory.domain.jobs import Job, JobStatus
from agent_memory.observability import annotate, get_logger, record_job, span

_logger = get_logger("agent_memory.application.extraction_worker")


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
        with span(
            "extraction.run_once",
            action="extraction.run_once",
            tenant_id=tenant_id,
            worker_id=worker_id,
            extractor_version=self._extractor.version,
        ):
            result = await self._run_once(tenant_id, worker_id)
            annotate(
                job_id=result.job_id,
                outcome=result.outcome,
                reason_code=result.reason_code,
            )
            _logger.event(
                "extraction.job",
                tenant_id=tenant_id,
                worker_id=worker_id,
                job_id=result.job_id,
                outcome=result.outcome,
                reason_code=result.reason_code,
            )
            record_job(outcome=result.outcome, reason_code=result.reason_code)
            return result

    async def _run_once(self, tenant_id: UUID, worker_id: str) -> WorkerResult:
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
                raise ExtractorVersionMismatch("EXTRACTOR_VERSION_MISMATCH")
            event = await self._backend.load_event(tenant_id, event_id)
            reason = "JOB_SUCCEEDED"
            try:
                candidates = await self._extractor.extract(event)
            except RetryableExtractionError:
                fallback = getattr(self._extractor, "fallback", None)
                if job.attempts < job.max_attempts or fallback is None:
                    raise
                candidates = await fallback.extract(event)
                if not candidates:
                    raise
                reason = "RULE_FALLBACK_EXHAUSTED"
            annotate(event_id=event_id, candidate_count=len(candidates))
            if any(candidate.scope != event.draft.scope for candidate in candidates):
                raise InvalidEvent("candidate scope expansion")
            if reason == "JOB_SUCCEEDED":
                reason = getattr(self._extractor, "last_reason", reason)
            job = replace(
                job,
                payload={
                    **job.payload,
                    "extraction_reason": reason,
                    "extraction_failure": getattr(self._extractor, "last_failure", "NONE"),
                },
            )
            await self._backend.commit_candidates(
                tenant_id,
                job,
                worker_id,
                event,
                candidates,
                self._now(),
            )
            return WorkerResult(job.job_id, "succeeded", reason)
        except LeaseLost:
            return WorkerResult(job.job_id, "lease_lost", "LEASE_LOST")
        except (InvalidEvent, KeyError, TypeError, ValueError) as error:
            code = (
                "EXTRACTOR_VERSION_MISMATCH"
                if isinstance(error, ExtractorVersionMismatch)
                else "INVALID_EVENT_FOR_EXTRACTION"
            )
            return await self._failure(job, tenant_id, worker_id, code, retryable=False)
        except RetryableExtractionError as error:
            return await self._failure(job, tenant_id, worker_id, error.code, retryable=True)

    async def _failure(
        self, job: Job, tenant_id: UUID, worker_id: str, code: str, *, retryable: bool
    ) -> WorkerResult:
        try:
            failed = await self._backend.fail_job(
                tenant_id, job.job_id, worker_id, self._now(), code, retryable=retryable
            )
        except LeaseLost:
            return WorkerResult(job.job_id, "lease_lost", "LEASE_LOST")
        outcome: Literal["dead", "retry_wait"] = (
            "dead" if failed.status is JobStatus.DEAD else "retry_wait"
        )
        return WorkerResult(job.job_id, outcome, code)
