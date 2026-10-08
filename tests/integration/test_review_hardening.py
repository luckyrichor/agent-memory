from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select, text

from agent_memory.application.commands import CorrectMemoryCommand, RememberMemoryCommand
from agent_memory.application.explicit_memory import ExplicitMemoryService
from agent_memory.application.retrieval import RetrievalQuery
from agent_memory.domain.enums import MemoryType, ScopeKind
from agent_memory.domain.models import MemoryScope
from agent_memory.domain.principal import RequestPrincipal
from agent_memory.infrastructure.db import (
    create_engine,
    create_session_factory,
    session_for_principal,
)
from agent_memory.infrastructure.orm import (
    AuditLogRow,
    IdempotencyRecordRow,
    JobRow,
    MemoryEmbeddingRow,
)
from agent_memory.infrastructure.queue_admin import PostgresQueueAdmin
from agent_memory.infrastructure.repositories import (
    PostgresAuditSink,
    PostgresIdempotencyRepository,
    PostgresMemoryRepository,
)
from agent_memory.infrastructure.retrieval import PostgresCandidateProvider


def principal():
    return RequestPrincipal(
        uuid4(), uuid4(), frozenset(), frozenset({"memory:read", "memory:write"}), frozenset()
    )


def service(session, who, now):
    return ExplicitMemoryService(
        memory_repository=PostgresMemoryRepository(session),
        idempotency_repository=PostgresIdempotencyRepository(session, lambda: now),
        audit_sink=PostgresAuditSink(session, new_id=uuid4, now=lambda: now),
        new_id=uuid4,
        now=lambda: now,
    )


async def test_chinese_keyword_before_after_and_tenant_isolation(app_database_url):
    engine = create_engine(app_database_url)
    sessions = create_session_factory(engine)
    who = principal()
    try:
        async with session_for_principal(sessions, who) as session:
            await service(session, who, datetime.now(UTC)).remember(
                RememberMemoryCommand(
                    "部署失败时先检查配置文件",
                    MemoryType.SEMANTIC,
                    MemoryScope(ScopeKind.TENANT, None, None),
                    "zh",
                ),
                who,
            )
            before = await session.scalar(
                text(
                    "SELECT to_tsvector('simple', '部署失败时先检查配置文件') "
                    "@@ plainto_tsquery('simple', '配置文件')"
                )
            )
            assert before is False
            after = await PostgresCandidateProvider(session).candidates(
                RetrievalQuery("配置文件"), who
            )
            assert len(after) == 1 and after[0].channel == "lexical"
            other = replace(who, tenant_id=uuid4())
            assert (
                await PostgresCandidateProvider(session).candidates(
                    RetrievalQuery("配置文件"), other
                )
                == []
            )
            tokens = await session.scalar(text("SELECT memory_lexical_tokens('部署失败 Java17')"))
            assert set(tokens.split()) == {"部署", "署失", "失败", "java17"}
    finally:
        await engine.dispose()


async def test_correction_reason_pagination_and_audit_in_postgres(app_database_url):
    engine = create_engine(app_database_url)
    sessions = create_session_factory(engine)
    who, now = principal(), datetime.now(UTC)
    try:
        async with session_for_principal(sessions, who) as session:
            usecase = service(session, who, now)
            created = await usecase.remember(
                RememberMemoryCommand(
                    "Java17",
                    MemoryType.SEMANTIC,
                    MemoryScope(ScopeKind.TENANT, None, None),
                    "create",
                ),
                who,
            )
            for revision in range(1, 4):
                await usecase.correct(
                    CorrectMemoryCommand(
                        created.memory_id, revision, f"Java{17 + revision}", f"upgrade {revision}"
                    ),
                    who,
                )
        async with session_for_principal(sessions, who) as session:
            repo = PostgresMemoryRepository(session)
            assert len((await repo.get(who.tenant_id, created.memory_id)).versions) == 1
            first, next_offset = await service(session, who, now).versions(
                created.memory_id, who, 2, 0
            )
            second, end = await service(session, who, now).versions(
                created.memory_id, who, 2, next_offset
            )
            assert [v.reason for v in (*first, *second)] == [
                None,
                "upgrade 1",
                "upgrade 2",
                "upgrade 3",
            ]
            assert end is None and next_offset == 2
            audits = list(
                await session.scalars(
                    select(AuditLogRow).where(
                        AuditLogRow.tenant_id == who.tenant_id,
                        AuditLogRow.action == "memory.correct",
                    )
                )
            )
            assert {a.metadata_json["reason"] for a in audits} == {
                "upgrade 1",
                "upgrade 2",
                "upgrade 3",
            }
    finally:
        await engine.dispose()


async def test_queue_admin_is_bounded_tenant_scoped_and_does_not_steal_leases(app_database_url):
    engine = create_engine(app_database_url)
    sessions = create_session_factory(engine)
    who, other, now = principal(), principal(), datetime.now(UTC)
    try:
        for owner in (who, other):
            async with session_for_principal(sessions, owner) as session:
                for state in ("dead", "running", "pending", "dead"):
                    session.add(
                        JobRow(
                            tenant_id=owner.tenant_id,
                            job_id=uuid4(),
                            job_type="extract_event",
                            idempotency_key=str(uuid4()),
                            payload={"event_id": str(uuid4()), "extractor_version": "old"},
                            status=state,
                            attempts=5 if state == "dead" else 1,
                            max_attempts=5,
                            available_at=now,
                            created_at=now,
                            updated_at=now,
                            leased_until=now + timedelta(seconds=30)
                            if state == "running"
                            else None,
                            lease_owner="live" if state == "running" else None,
                            last_error_code="HTTP_503",
                        )
                    )
        admin = PostgresQueueAdmin(sessions, who.tenant_id)
        assert (await admin.status())["counts"] == {"dead": 2, "running": 1, "pending": 1}
        assert await admin.requeue(job_type="extract_event", limit=1) == 1
        assert (
            await admin.requeue(
                job_type="extract_event", limit=1, old_version="old", new_version="new"
            )
            == 1
        )
        assert (
            await admin.requeue(
                job_type="extract_event", limit=100, old_version="old", new_version="new"
            )
            == 2
        )
        assert (
            await admin.requeue(
                job_type="extract_event", limit=100, old_version="old", new_version="new"
            )
            == 0
        )
        assert (await admin.status(version="old"))["counts"] == {"dead": 3, "running": 1}
        assert (await admin.status(version="new"))["counts"] == {"pending": 3}
        assert (await PostgresQueueAdmin(sessions, other.tenant_id).status())["counts"]["dead"] == 2
    finally:
        await engine.dispose()


async def test_retention_cleanup_and_model_rebuild_batches(app_database_url):
    engine = create_engine(app_database_url)
    sessions = create_session_factory(engine)
    who, now = principal(), datetime.now(UTC)
    try:
        async with session_for_principal(sessions, who) as session:
            for index in range(3):
                created = await service(session, who, now - timedelta(days=8)).remember(
                    RememberMemoryCommand(
                        f"content {index}",
                        MemoryType.SEMANTIC,
                        MemoryScope(ScopeKind.TENANT, None, None),
                        f"k{index}",
                    ),
                    who,
                )
                session.add(
                    MemoryEmbeddingRow(
                        tenant_id=who.tenant_id,
                        memory_version_id=created.version_id,
                        model="old",
                        embedding=[1.0] * 1024,
                        updated_at=now,
                    )
                )
        admin = PostgresQueueAdmin(sessions, who.tenant_id)
        assert await admin.cleanup_idempotency(limit=1) == 1
        assert await admin.cleanup_idempotency(limit=100) == 2
        assert await admin.cleanup_idempotency(limit=100) == 0
        assert await admin.rebuild_model("old", "op1", limit=1) == 1
        assert await admin.rebuild_model("old", "op1", limit=1) == 1
        assert await admin.rebuild_model("old", "op1", limit=10) == 1
        assert await admin.rebuild_model("old", "op1", limit=10) == 0
        async with session_for_principal(sessions, who) as session:
            assert list(await session.scalars(select(IdempotencyRecordRow))) == []
    finally:
        await engine.dispose()


async def test_postgres_worker_claim_only_matches_configured_extractor(app_database_url):
    from agent_memory.infrastructure.event_repositories import PostgresJobQueue

    engine = create_engine(app_database_url)
    sessions = create_session_factory(engine)
    who, now = principal(), datetime.now(UTC)
    try:
        async with session_for_principal(sessions, who) as session:
            for version in ('old', 'new'):
                session.add(JobRow(tenant_id=who.tenant_id, job_id=uuid4(), job_type='extract_event',
                    idempotency_key=version, payload={'event_id': str(uuid4()), 'extractor_version': version},
                    status='pending', attempts=0, max_attempts=5, available_at=now,
                    created_at=now, updated_at=now))
        async with session_for_principal(sessions, who) as session:
            queue = PostgresJobQueue(session)
            claimed = await queue.claim(who.tenant_id, 'worker', now, timedelta(seconds=30),
                                        extractor_version='new')
            assert claimed is not None and claimed.payload['extractor_version'] == 'new'
            assert await queue.claim(who.tenant_id, 'worker', now, timedelta(seconds=30),
                                     extractor_version='new') is None
            old = await session.scalar(select(JobRow).where(JobRow.tenant_id == who.tenant_id,
                                                           JobRow.idempotency_key == 'old'))
            assert old.status == 'pending' and old.attempts == 0
    finally:
        await engine.dispose()
