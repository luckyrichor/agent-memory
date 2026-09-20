"""The extraction worker emits the same three signals as the API path."""

import json
import logging
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from agent_memory.application.extraction_worker import ExtractionWorker
from agent_memory.domain.enums import (
    AuthorityLevel,
    MemoryType,
    ScopeKind,
    VerificationStatus,
)
from agent_memory.domain.events import Event, EventDraft, EventType, MemoryCandidate
from agent_memory.domain.jobs import Job, JobStatus
from agent_memory.domain.models import MemoryScope
from agent_memory.observability import set_meter_provider, set_tracer_provider

TENANT_ID = UUID("38000000-0000-0000-0000-000000000001")
USER_ID = UUID("38000000-0000-0000-0000-000000000002")
EVENT_ID = UUID("38000000-0000-0000-0000-000000000003")
JOB_ID = UUID("38000000-0000-0000-0000-000000000004")
NOW = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)
PRIVATE_SUMMARY = "deploy failed because the staging token expired"


def event() -> Event:
    return Event(
        tenant_id=TENANT_ID,
        event_id=EVENT_ID,
        actor_user_id=USER_ID,
        received_at=NOW,
        draft=EventDraft(
            idempotency_key="observed-job",
            session_id="observed-session",
            sequence_number=1,
            event_type=EventType.TOOL_RESULT,
            agent_id="coding_agent",
            occurred_at=NOW,
            scope=MemoryScope(ScopeKind.WORKSPACE, "project-a", None),
            payload={"tool_name": "build", "exit_code": 1, "summary": PRIVATE_SUMMARY},
        ),
    )


def pending_job() -> Job:
    return Job(
        tenant_id=TENANT_ID,
        job_id=JOB_ID,
        job_type="extract_event",
        idempotency_key=f"extract_event:{EVENT_ID}:observed-v1",
        payload={"event_id": str(EVENT_ID), "extractor_version": "observed-v1"},
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


class CommittingBackend:
    def __init__(self) -> None:
        self.job = pending_job()
        self.committed: tuple[MemoryCandidate, ...] = ()

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
        self.committed = candidates

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
        raise AssertionError("unexpected failure path")


class EchoExtractor:
    @property
    def version(self) -> str:
        return "observed-v1"

    async def extract(self, source: Event) -> tuple[MemoryCandidate, ...]:
        return (
            MemoryCandidate(
                content=PRIVATE_SUMMARY,
                memory_type=MemoryType.EPISODIC,
                scope=source.draft.scope,
                confidence=1.0,
                utility=0.5,
                authority_level=AuthorityLevel.TOOL_VERIFIED,
                verification_status=VerificationStatus.VERIFIED,
            ),
        )


@pytest.fixture
def pipeline() -> Iterator[tuple[InMemorySpanExporter, InMemoryMetricReader]]:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    set_tracer_provider(provider)
    reader = InMemoryMetricReader()
    set_meter_provider(MeterProvider(metric_readers=[reader]))
    try:
        yield exporter, reader
    finally:
        set_tracer_provider(None)
        set_meter_provider(None)


@pytest.mark.asyncio
async def test_a_processed_job_produces_a_span_a_log_line_and_a_counter(
    pipeline: tuple[InMemorySpanExporter, InMemoryMetricReader],
    caplog: pytest.LogCaptureFixture,
) -> None:
    exporter, reader = pipeline
    backend = CommittingBackend()
    worker = ExtractionWorker(
        backend,
        EchoExtractor(),
        now=lambda: NOW,
        lease_duration=timedelta(seconds=30),
    )

    with caplog.at_level(logging.INFO):
        result = await worker.run_once(TENANT_ID, "worker-a")

    assert result.outcome == "succeeded"
    assert len(backend.committed) == 1

    span = next(s for s in exporter.get_finished_spans() if s.name == "extraction.run_once")
    assert span.attributes is not None
    assert span.attributes["outcome"] == "succeeded"
    assert span.attributes["job_id"] == str(JOB_ID)
    assert span.attributes["candidate_count"] == 1
    assert span.attributes["extractor_version"] == "observed-v1"

    logged = [record for record in caplog.records if record.getMessage() == "extraction.job"]
    assert len(logged) == 1

    data = reader.get_metrics_data()
    assert data is not None
    counted = [
        point
        for resource in data.resource_metrics
        for scope in resource.scope_metrics
        for metric in scope.metrics
        if metric.name == "agent_memory.worker.jobs"
        for point in metric.data.data_points
    ]
    assert [point.attributes["outcome"] for point in counted] == ["succeeded"]  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_worker_telemetry_never_carries_the_extracted_content(
    pipeline: tuple[InMemorySpanExporter, InMemoryMetricReader],
    caplog: pytest.LogCaptureFixture,
) -> None:
    exporter, _ = pipeline
    worker = ExtractionWorker(
        CommittingBackend(),
        EchoExtractor(),
        now=lambda: NOW,
        lease_duration=timedelta(seconds=30),
    )

    with caplog.at_level(logging.INFO):
        await worker.run_once(TENANT_ID, "worker-a")

    exported = json.dumps([json.loads(s.to_json()) for s in exporter.get_finished_spans()])
    logged = json.dumps(
        [getattr(record, "agent_memory_fields", {}) for record in caplog.records],
        default=str,
    )
    assert PRIVATE_SUMMARY not in exported
    assert PRIVATE_SUMMARY not in logged
