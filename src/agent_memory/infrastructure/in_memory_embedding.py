from datetime import datetime, timedelta
from uuid import UUID, uuid4

from agent_memory.domain.errors import MemoryNotFound
from agent_memory.domain.jobs import Job, JobStatus


class InMemoryEmbeddingBackend:
    def __init__(self) -> None:
        self.contents: dict[tuple[UUID, UUID], str] = {}
        self.jobs: dict[UUID, Job] = {}
        self.vectors: dict[tuple[UUID, UUID], tuple[str, list[float]]] = {}

    async def enqueue(self, tenant: UUID, version: UUID, content: str, now: datetime) -> None:
        self.contents[tenant, version] = content
        await self.rebuild(tenant, version, "initial", now)

    async def rebuild(self, tenant: UUID, version: UUID, key: str, now: datetime) -> None:
        await self.load_content(tenant, version)
        job_key = f"{version}:{key}"
        if any(j.tenant_id == tenant and j.idempotency_key == job_key for j in self.jobs.values()):
            return
        job = Job(
            tenant,
            uuid4(),
            "embed_memory",
            job_key,
            {"version_id": str(version)},
            JobStatus.PENDING,
            0,
            5,
            now,
            None,
            None,
            None,
            now,
            now,
        )
        self.jobs[job.job_id] = job

    async def claim(
        self, tenant: UUID, worker: str, now: datetime, duration: timedelta
    ) -> Job | None:
        for job in self.jobs.values():
            if job.tenant_id != tenant:
                continue
            if (
                job.status in {JobStatus.PENDING, JobStatus.RETRY_WAIT}
                and job.available_at <= now
                or job.status is JobStatus.RUNNING
                and job.leased_until is not None
                and job.leased_until <= now
            ):
                claimed = job.claim(worker, now, duration)
                self.jobs[job.job_id] = claimed
                return claimed
        return None

    async def load_content(self, tenant: UUID, version: UUID) -> str:
        if (tenant, version) not in self.contents:
            raise MemoryNotFound(str(version))
        return self.contents[tenant, version]

    async def complete(
        self, job: Job, worker: str, model: str, vector: list[float], now: datetime
    ) -> None:
        succeeded = self.jobs[job.job_id].succeed(worker, now)
        self.vectors[job.tenant_id, UUID(str(job.payload["version_id"]))] = (model, vector)
        self.jobs[job.job_id] = succeeded

    async def fail(
        self,
        job: Job,
        worker: str,
        now: datetime,
        *,
        code: str = "EMBEDDING_FAILED",
        retryable: bool = True,
        retry_after: timedelta | None = None,
    ) -> Job:
        failed = self.jobs[job.job_id].fail(
            worker, now, code, retryable=retryable, retry_after=retry_after
        )
        self.jobs[job.job_id] = failed
        return failed
