import hashlib
from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agent_memory.application.embedding import DIMENSIONS
from agent_memory.domain.errors import MemoryNotFound
from agent_memory.domain.jobs import Job
from agent_memory.domain.principal import RequestPrincipal
from agent_memory.infrastructure.db import session_for_principal
from agent_memory.infrastructure.event_repositories import PostgresJobQueue
from agent_memory.infrastructure.orm import JobRow, MemoryEmbeddingRow, MemoryVersionRow


class FixtureEmbeddingProvider:
    """Deterministic pipeline fixture, NOT a semantic embedding model."""
    model = "fixture-sha256-1024-v1"

    async def embed(self, content: str) -> list[float]:
        digest = hashlib.sha256(content.encode()).digest()
        return [(digest[i % len(digest)] - 127.5) / 127.5 for i in range(DIMENSIONS)]


class HTTPEmbeddingProvider:
    """Vendor-neutral endpoint: POST {model,input}, response data[0].embedding."""
    def __init__(self, client: httpx.AsyncClient, *, endpoint: str, model: str,
                 token: str, protocol: Literal["openai", "ark"] = "openai") -> None:
        self.client = client
        self.endpoint = endpoint
        self.model = model
        self.token = token
        self.protocol = protocol

    async def embed(self, content: str) -> list[float]:
        payload: dict[str, object] = {"model": self.model, "input": content}
        if self.protocol == "ark":
            payload.update(input=[{"type": "text", "text": content}], dimensions=DIMENSIONS,
                           encoding_format="float")
        response = await self.client.post(self.endpoint, json=payload,
                                         headers={"Authorization": f"Bearer {self.token}"})
        response.raise_for_status()
        data = response.json()["data"]
        values = data["embedding"] if self.protocol == "ark" else data[0]["embedding"]
        return [float(x) for x in values]


class PostgresEmbeddingBackend:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    @staticmethod
    def principal(tenant: UUID) -> RequestPrincipal:
        return RequestPrincipal(tenant, UUID(int=0), frozenset({"embedding_worker"}),
                                frozenset({"queue:work"}), frozenset())

    async def claim(self, tenant: UUID, worker: str, now: datetime,
                    duration: timedelta) -> Job | None:
        async with session_for_principal(self.sessions, self.principal(tenant)) as session:
            return await PostgresJobQueue(session).claim(tenant, worker, now, duration, "embed_memory")

    async def load_content(self, tenant: UUID, version: UUID) -> str:
        async with session_for_principal(self.sessions, self.principal(tenant)) as session:
            content = await session.scalar(select(MemoryVersionRow.content).where(
                MemoryVersionRow.tenant_id == tenant, MemoryVersionRow.memory_version_id == version))
            if content is None:
                raise MemoryNotFound(str(version))
            return content

    async def complete(self, job: Job, worker: str, model: str, vector: list[float],
                       now: datetime) -> None:
        async with session_for_principal(self.sessions, self.principal(job.tenant_id)) as session:
            # Lease check + vector upsert + success marker are one transaction.
            await PostgresJobQueue(session).succeed(job.tenant_id, job.job_id, worker, now)
            statement = insert(MemoryEmbeddingRow).values(
                tenant_id=job.tenant_id, memory_version_id=UUID(str(job.payload["version_id"])),
                model=model, embedding=vector, updated_at=now)
            await session.execute(statement.on_conflict_do_update(
                index_elements=["tenant_id", "memory_version_id"],
                set_={"model": model, "embedding": vector, "updated_at": now}))

    async def fail(self, job: Job, worker: str, now: datetime) -> Job:
        async with session_for_principal(self.sessions, self.principal(job.tenant_id)) as session:
            return await PostgresJobQueue(session).fail(job.tenant_id, job.job_id, worker, now,
                                                       "EMBEDDING_FAILED", retryable=True)

    async def rebuild(self, tenant: UUID, version: UUID, key: str, now: datetime) -> None:
        # New request key permits rebuilding succeeded/dead jobs; replay is deduplicated.
        await self.load_content(tenant, version)
        async with session_for_principal(self.sessions, self.principal(tenant)) as session:
            await session.execute(insert(JobRow).values(
                tenant_id=tenant, job_id=uuid4(), job_type="embed_memory",
                idempotency_key=f"rebuild:{version}:{key}", payload={"version_id": str(version)},
                status="pending", attempts=0, max_attempts=5, available_at=now,
                created_at=now, updated_at=now).on_conflict_do_nothing(
                    index_elements=["tenant_id", "job_type", "idempotency_key"]))
