from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from agent_memory.application.extraction_worker import ExtractionWorker
from agent_memory.domain.enums import ScopeKind
from agent_memory.domain.errors import RetryableExtractionError
from agent_memory.domain.events import Event, EventDraft, EventType, MemoryCandidate
from agent_memory.domain.jobs import Job, JobStatus
from agent_memory.domain.models import MemoryScope

TENANT_ID = UUID("37000000-0000-0000-0000-000000000001")
USER_ID = UUID("37000000-0000-0000-0000-000000000002")
EVENT_ID = UUID("37000000-0000-0000-0000-000000000003")
JOB_ID = UUID("37000000-0000-0000-0000-000000000004")
NOW = datetime(2026, 8, 30, 20, 0, tzinfo=UTC)


def event() -> Event:
    return Event(
        tenant_id=TENANT_ID,
        event_id=EVENT_ID,
        actor_user_id=USER_ID,
        received_at=NOW,
        draft=EventDraft(
            idempotency_key="worker-retry",
            session_id="worker-session",
            sequence_number=1,
            event_type=EventType.TOOL_RESULT,
            agent_id="coding_agent",
            occurred_at=NOW,
            scope=MemoryScope(ScopeKind.WORKSPACE, "project-a", None),
            payload={"tool_name": "build", "exit_code": 1, "summary": "secret"},
        ),
    )


def pending_job() -> Job:
    return Job(
        tenant_id=TENANT_ID,
        job_id=JOB_ID,
        job_type="extract_event",
        idempotency_key=f"extract_event:{EVENT_ID}:failing-v1",
        payload={"event_id": str(EVENT_ID), "extractor_version": "failing-v1"},
        status=JobStatus.PENDING,
        attempts=0,
        max_attempts=5,
        available_at=NOW,
        leased_until=None,
        lease_owner=None,
        last_error_code=None,
        created_at=NOW,
        updated_at=NOW,
    )


class RecordingBackend:
    def __init__(self) -> None:
        self.job = pending_job()

    async def claim(
        self,
        tenant_id: UUID,
        worker_id: str,
        now: datetime,
        lease_duration: timedelta,
    ) -> Job | None:
        self.job = self.job.claim(worker_id, now, lease_duration)
        return self.job

    async def load_event(self, tenant_id: UUID, event_id: UUID) -> Event:
        return event()

    async def commit_candidates(
        self,
        tenant_id: UUID,
        job: Job,
        worker_id: str,
        loaded_event: Event,
        candidates: tuple[MemoryCandidate, ...],
        now: datetime,
    ) -> None:
        raise AssertionError("unexpected candidate commit")

    async def fail_job(
        self,
        tenant_id: UUID,
        job_id: UUID,
        worker_id: str,
        now: datetime,
        error_code: str,
        *,
        retryable: bool,
    ) -> Job:
        self.job = self.job.fail(
            worker_id,
            now,
            error_code,
            retryable=retryable,
        )
        return self.job


class FailingExtractor:
    @property
    def version(self) -> str:
        return "failing-v1"

    async def extract(self, event: Event) -> tuple[MemoryCandidate, ...]:
        raise RetryableExtractionError("provider response contained private content")


@pytest.mark.asyncio
async def test_retryable_extraction_failure_moves_job_to_retry_wait_safely() -> None:
    backend = RecordingBackend()
    worker = ExtractionWorker(
        backend,
        FailingExtractor(),
        now=lambda: NOW,
        lease_duration=timedelta(seconds=30),
    )

    result = await worker.run_once(TENANT_ID, "worker-a")

    assert result.job_id == JOB_ID
    assert result.outcome == "retry_wait"
    assert result.reason_code == "EXTRACTION_FAILED"
    assert backend.job.status is JobStatus.RETRY_WAIT
    assert backend.job.last_error_code == "EXTRACTION_FAILED"
