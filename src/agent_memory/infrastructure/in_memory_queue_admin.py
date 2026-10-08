"""Evaluation adapter for the same tenant-scoped queue operations."""

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from agent_memory.domain.jobs import Job, JobStatus
from agent_memory.infrastructure.in_memory import InMemoryIdempotencyRepository


class InMemoryQueueAdmin:
    def __init__(
        self,
        jobs: dict[UUID, Job],
        tenant: UUID,
        *,
        now: Callable[[], datetime] | None = None,
        embeddings: dict[tuple[UUID, UUID], str] | None = None,
        idempotency: InMemoryIdempotencyRepository | None = None,
    ) -> None:
        self.jobs, self.tenant = jobs, tenant
        self.now = now or (lambda: datetime.now(UTC))
        self.embeddings = embeddings or {}
        self.idempotency = idempotency

    async def status(
        self, *, job_type: str | None = None, version: str | None = None
    ) -> dict[str, object]:
        jobs = sorted(
            (
                j
                for j in self.jobs.values()
                if j.tenant_id == self.tenant
                and (job_type is None or j.job_type == job_type)
                and (version is None or j.payload.get("extractor_version") == version)
            ),
            key=lambda j: (j.created_at, j.job_id),
        )
        counts: dict[str, int] = {}
        for job in jobs:
            counts[job.status.value] = counts.get(job.status.value, 0) + 1
        active = [
            j.created_at
            for j in jobs
            if j.status in {JobStatus.PENDING, JobStatus.RETRY_WAIT, JobStatus.RUNNING}
        ]
        return {
            "counts": counts,
            "oldest_age_seconds": max(0, (self.now() - min(active)).total_seconds())
            if active
            else 0,
            "dead": [
                {
                    "job_id": str(j.job_id),
                    "error_code": j.last_error_code,
                    "attempts": j.attempts,
                    "job_type": j.job_type,
                }
                for j in jobs
                if j.status == JobStatus.DEAD
            ][:100],
            "dead_limit": 100,
        }

    async def requeue(
        self,
        *,
        job_type: str,
        limit: int,
        old_version: str | None = None,
        new_version: str | None = None,
    ) -> int:
        if not 1 <= limit <= 1000 or bool(old_version) != bool(new_version):
            raise ValueError("invalid batch or extractor versions")
        if old_version and job_type != "extract_event":
            raise ValueError("extractor migration requires extract_event jobs")
        count, at = 0, self.now()
        for job in sorted(self.jobs.values(), key=lambda j: (j.created_at, j.job_id)):
            if job.tenant_id != self.tenant or job.job_type != job_type or count >= limit:
                continue
            if old_version:
                if (
                    job.payload.get("extractor_version") != old_version
                    or job.status not in {JobStatus.PENDING, JobStatus.RETRY_WAIT, JobStatus.DEAD}
                    or job.last_error_code == "EXTRACTOR_MIGRATED"
                ):
                    continue
                event_id = str(job.payload["event_id"])
                key = f"extract_event:{event_id}:{new_version}"
                if not any(
                    j.tenant_id == self.tenant
                    and j.job_type == job_type
                    and j.idempotency_key == key
                    for j in self.jobs.values()
                ):
                    new = Job(
                        self.tenant,
                        uuid4(),
                        job_type,
                        key,
                        {"event_id": event_id, "extractor_version": new_version},
                        JobStatus.PENDING,
                        0,
                        5,
                        at,
                        None,
                        None,
                        None,
                        at,
                        at,
                    )
                    self.jobs[new.job_id] = new
                self.jobs[job.job_id] = replace(
                    job,
                    status=JobStatus.DEAD,
                    last_error_code="EXTRACTOR_MIGRATED",
                    leased_until=None,
                    lease_owner=None,
                    available_at=at,
                    updated_at=at,
                )
            else:
                if job.status != JobStatus.DEAD or job.last_error_code == "EXTRACTOR_MIGRATED":
                    continue
                self.jobs[job.job_id] = replace(
                    job,
                    status=JobStatus.PENDING,
                    attempts=0,
                    last_error_code=None,
                    leased_until=None,
                    lease_owner=None,
                    available_at=at,
                    updated_at=at,
                )
            count += 1
        return count

    async def rebuild_model(self, model: str, key: str, *, limit: int = 1000) -> int:
        if not model or not key or not 1 <= limit <= 1000:
            raise ValueError("invalid rebuild")
        count, at = 0, self.now()
        for (tenant, version), current_model in sorted(self.embeddings.items()):
            identity = f"model-rebuild:{version}:{key}"
            if (
                tenant != self.tenant
                or current_model != model
                or count >= limit
                or any(
                    j.tenant_id == self.tenant
                    and j.idempotency_key == identity
                    and j.job_type == "embed_memory"
                    for j in self.jobs.values()
                )
            ):
                continue
            new = Job(
                self.tenant,
                uuid4(),
                "embed_memory",
                identity,
                {"version_id": str(version)},
                JobStatus.PENDING,
                0,
                5,
                at,
                None,
                None,
                None,
                at,
                at,
            )
            self.jobs[new.job_id] = new
            count += 1
        return count

    async def cleanup_idempotency(self, *, limit: int = 1000) -> int:
        if not 1 <= limit <= 1000:
            raise ValueError("invalid batch")
        if self.idempotency is None:
            return 0
        count = 0
        for identity, created in list(self.idempotency._created.items()):
            if (
                identity[0] == self.tenant
                and created <= self.now() - timedelta(days=7)
                and count < limit
            ):
                self.idempotency._created.pop(identity)
                self.idempotency._records.pop(identity)
                count += 1
        return count
