from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from agent_memory.application.commands import RememberMemoryCommand
from agent_memory.application.embedding import EmbeddingWorker
from agent_memory.application.explicit_memory import ExplicitMemoryService
from agent_memory.domain.enums import MemoryType, ScopeKind
from agent_memory.domain.errors import LeaseLost
from agent_memory.domain.models import MemoryScope
from agent_memory.domain.principal import RequestPrincipal
from agent_memory.infrastructure.db import (
    create_engine,
    create_session_factory,
    session_for_principal,
)
from agent_memory.infrastructure.embedding import FixtureEmbeddingProvider, PostgresEmbeddingBackend
from agent_memory.infrastructure.orm import JobRow, MemoryEmbeddingRow
from agent_memory.infrastructure.repositories import (
    PostgresAuditSink,
    PostgresIdempotencyRepository,
    PostgresMemoryRepository,
)


@pytest.mark.asyncio
async def test_transactional_embedding_retry_restart_rebuild_and_rls(app_database_url: str) -> None:
    tenant, user = uuid4(), uuid4()
    principal = RequestPrincipal(tenant, user, frozenset(), frozenset({"memory:write"}), frozenset())
    engine = create_engine(app_database_url)
    sessions = create_session_factory(engine)
    at = datetime.now(UTC)
    try:
        async with session_for_principal(sessions, principal) as session:
            service = ExplicitMemoryService(memory_repository=PostgresMemoryRepository(session),
                idempotency_repository=PostgresIdempotencyRepository(session, lambda: at),
                audit_sink=PostgresAuditSink(session, new_id=uuid4, now=lambda: at),
                new_id=uuid4, now=lambda: at)
            result = await service.remember(RememberMemoryCommand("embedding content",
                MemoryType.SEMANTIC, MemoryScope(ScopeKind.TENANT, None, None), "embedding-test"),
                principal)
        backend = PostgresEmbeddingBackend(sessions)
        async with session_for_principal(sessions, principal) as session:
            assert await session.scalar(select(func.count()).select_from(JobRow).where(
                JobRow.tenant_id == tenant, JobRow.job_type == "embed_memory")) == 1
            assert await session.scalar(select(func.count()).select_from(MemoryEmbeddingRow)) == 0

        class FailingProvider(FixtureEmbeddingProvider):
            async def embed(self, content: str) -> list[float]:
                raise RuntimeError("secret content must not appear in telemetry")

        worker = EmbeddingWorker(backend, FailingProvider())
        assert (await worker.run_once(tenant, "w1", now=at + timedelta(seconds=1))).outcome == "retry_wait"
        assert (await worker.run_once(tenant, "w1", now=at + timedelta(seconds=2))).outcome == "no_job"
        # New backend/worker simulates process restart; state remains in Postgres.
        restarted = PostgresEmbeddingBackend(sessions)
        ok = EmbeddingWorker(restarted, FixtureEmbeddingProvider())
        assert (await ok.run_once(tenant, "w2", now=at + timedelta(seconds=4))).outcome == "succeeded"
        async with session_for_principal(sessions, principal) as session:
            row = await session.scalar(select(MemoryEmbeddingRow))
            assert row is not None and row.memory_version_id == result.version_id
            assert len(row.embedding) == 1024
        other = PostgresEmbeddingBackend.principal(uuid4())
        async with session_for_principal(sessions, other) as session:
            assert await session.scalar(select(func.count()).select_from(MemoryEmbeddingRow)) == 0
        await backend.rebuild(tenant, result.version_id, "run-1", at)
        await backend.rebuild(tenant, result.version_id, "run-1", at)
        # Claim and abandon; expired lease recovers to another worker.
        job = await backend.claim(tenant, "abandoned", at + timedelta(seconds=5), timedelta(seconds=1))
        assert job is not None
        assert (await ok.run_once(tenant, "recovered", now=at + timedelta(seconds=7))).outcome == "succeeded"
        with pytest.raises(LeaseLost):
            await backend.complete(job, "abandoned", "invalid", [0.0]*1024, at + timedelta(seconds=8))
        async with session_for_principal(sessions, principal) as session:
            assert await session.scalar(select(func.count()).select_from(JobRow).where(
                JobRow.tenant_id == tenant, JobRow.job_type == "embed_memory")) == 2
            assert await session.scalar(select(func.count()).select_from(MemoryEmbeddingRow)) == 1
        # Rollback version insertion also rolls back its queued job.
        with pytest.raises(RuntimeError):
            async with session_for_principal(sessions, principal) as session:
                service = ExplicitMemoryService(memory_repository=PostgresMemoryRepository(session),
                    idempotency_repository=PostgresIdempotencyRepository(session, lambda: at),
                    audit_sink=PostgresAuditSink(session, new_id=uuid4, now=lambda: at),
                    new_id=uuid4, now=lambda: at)
                await service.remember(RememberMemoryCommand("rolled back", MemoryType.SEMANTIC,
                    MemoryScope(ScopeKind.TENANT, None, None), "rollback"), principal)
                raise RuntimeError("rollback")
        async with session_for_principal(sessions, principal) as session:
            assert await session.scalar(select(func.count()).select_from(JobRow)) == 2
    finally:
        await engine.dispose()
