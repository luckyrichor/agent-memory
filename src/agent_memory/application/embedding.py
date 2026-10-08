"""Durable async embedding jobs; provider I/O occurs outside database transactions."""

import asyncio
import math
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

from agent_memory.application.extraction_worker import WorkerResult
from agent_memory.application.provider_errors import classify
from agent_memory.domain.errors import LeaseLost
from agent_memory.domain.jobs import Job, JobStatus
from agent_memory.observability import get_logger, record_job, span

DIMENSIONS = 1024
_logger = get_logger("agent_memory.application.embedding")


class EmbeddingProvider(Protocol):
    model: str

    async def embed(self, content: str) -> list[float]: ...


class EmbeddingBackend(Protocol):
    async def claim(
        self, tenant: UUID, worker: str, now: datetime, duration: timedelta
    ) -> Job | None: ...
    async def load_content(self, tenant: UUID, version: UUID) -> str: ...
    async def complete(
        self, job: Job, worker: str, model: str, vector: list[float], now: datetime
    ) -> None: ...
    async def fail(
        self,
        job: Job,
        worker: str,
        now: datetime,
        *,
        code: str = "EMBEDDING_FAILED",
        retryable: bool = True,
        retry_after: timedelta | None = None,
    ) -> Job: ...
    async def rebuild(self, tenant: UUID, version: UUID, key: str, now: datetime) -> None: ...


class EmbeddingWorker:
    def __init__(
        self,
        backend: EmbeddingBackend,
        provider: EmbeddingProvider,
        *,
        timeout: float = 10,
        lease_seconds: float = 30,
    ) -> None:
        if timeout + 5 >= lease_seconds:
            raise ValueError("provider timeout exceeds lease budget")
        self.timeout, self.lease_seconds = timeout, lease_seconds
        self.backend = backend
        self.provider = provider

    async def run_once(
        self, tenant: UUID, worker: str, *, now: datetime | None = None
    ) -> WorkerResult:
        at = now or datetime.now(UTC)
        job = await self.backend.claim(tenant, worker, at, timedelta(seconds=self.lease_seconds))
        if job is None:
            return WorkerResult(None, "no_job", "NO_JOB_AVAILABLE")
        with span("embedding.run_once", tenant_id=tenant, job_id=job.job_id, worker_id=worker):
            try:
                content = await self.backend.load_content(
                    tenant, UUID(str(job.payload["version_id"]))
                )
                async with asyncio.timeout(self.timeout):
                    vector = await self.provider.embed(content)
                if (
                    len(vector) != DIMENSIONS
                    or not all(math.isfinite(x) for x in vector)
                    or not any(vector)
                ):
                    raise ValueError("invalid embedding")
                # Real completion time fences slow providers that outlive their lease.
                finished = at if now is not None else datetime.now(UTC)
                await self.backend.complete(job, worker, self.provider.model, vector, finished)
                result = WorkerResult(job.job_id, "succeeded", "EMBEDDING_SUCCEEDED")
            except LeaseLost:
                result = WorkerResult(job.job_id, "lease_lost", "LEASE_LOST")
            except Exception as error:  # noqa: BLE001 - provider boundary; persist retry, redact error text
                # Exceptions may contain credentials/content; never serialize their text.
                try:
                    finished = at if now is not None else datetime.now(UTC)
                    code, retryable, delay = classify(error, finished)
                    failed = await self.backend.fail(
                        job, worker, finished, code=code, retryable=retryable, retry_after=delay
                    )
                    result = WorkerResult(
                        job.job_id,
                        "dead" if failed.status is JobStatus.DEAD else "retry_wait",
                        code,
                    )
                except LeaseLost:
                    result = WorkerResult(job.job_id, "lease_lost", "LEASE_LOST")
            _logger.event(
                "embedding.job",
                job_id=job.job_id,
                outcome=result.outcome,
                reason_code=result.reason_code,
            )
            record_job(outcome=result.outcome, reason_code=result.reason_code)
            return result
