"""Tenant-scoped bounded operations. Never reclaim a live lease."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agent_memory.domain.principal import RequestPrincipal
from agent_memory.infrastructure.db import session_for_principal
from agent_memory.infrastructure.orm import (
    AuditLogRow,
    IdempotencyRecordRow,
    JobRow,
    MemoryEmbeddingRow,
    MemoryVersionRow,
)
from agent_memory.observability.metrics import record_queue_snapshot


class PostgresQueueAdmin:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], tenant: UUID) -> None:
        self.sessions, self.tenant = sessions, tenant
        self.principal = RequestPrincipal(
            tenant, UUID(int=0), frozenset({"queue_operator"}), frozenset(), frozenset()
        )

    async def status(
        self, *, job_type: str | None = None, version: str | None = None
    ) -> dict[str, object]:
        async with session_for_principal(self.sessions, self.principal) as session:
            filters = [JobRow.tenant_id == self.tenant]
            if job_type:
                filters.append(JobRow.job_type == job_type)
            if version:
                filters.append(JobRow.payload["extractor_version"].astext == version)
            counts = await session.execute(
                select(JobRow.status, func.count()).where(*filters).group_by(JobRow.status)
            )
            oldest = await session.scalar(
                select(func.min(JobRow.created_at)).where(
                    *filters, JobRow.status.in_(["pending", "retry_wait", "running"])
                )
            )
            dead = await session.scalars(
                select(JobRow)
                .where(*filters, JobRow.status == "dead")
                .order_by(JobRow.created_at, JobRow.job_id)
                .limit(100)
            )
            snapshot = {status: count for status, count in counts}
            age = max(0, (datetime.now(UTC) - oldest).total_seconds()) if oldest else 0
            record_queue_snapshot(snapshot, age)
            return {
                "counts": snapshot,
                "oldest_age_seconds": max(0, (datetime.now(UTC) - oldest).total_seconds())
                if oldest
                else 0,
                "dead": [
                    {
                        "job_id": str(j.job_id),
                        "error_code": j.last_error_code,
                        "attempts": j.attempts,
                        "job_type": j.job_type,
                    }
                    for j in dead
                ],
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
        if not 1 <= limit <= 1000:
            raise ValueError("limit must be 1..1000")
        if old_version and job_type != "extract_event":
            raise ValueError("extractor migration requires extract_event jobs")
        if bool(old_version) != bool(new_version):
            raise ValueError("both extractor versions are required")
        async with session_for_principal(self.sessions, self.principal) as session:
            filters = [JobRow.tenant_id == self.tenant, JobRow.job_type == job_type]
            if old_version:
                filters.extend(
                    [
                        JobRow.payload["extractor_version"].astext == old_version,
                        JobRow.status.in_(["pending", "retry_wait", "dead"]),
                        (
                            JobRow.last_error_code.is_(None)
                            | (JobRow.last_error_code != "EXTRACTOR_MIGRATED")
                        ),
                    ]
                )
            else:
                filters.extend(
                    [
                        JobRow.status == "dead",
                        JobRow.last_error_code.is_(None)
                        | (JobRow.last_error_code != "EXTRACTOR_MIGRATED"),
                    ]
                )
            rows = list(
                await session.scalars(
                    select(JobRow)
                    .where(*filters)
                    .order_by(JobRow.created_at, JobRow.job_id)
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            )
            now = datetime.now(UTC)
            for row in rows:
                # Keep old jobs for provenance; new version gets a distinct durable job.
                if new_version:
                    event_id = str(row.payload["event_id"])
                    await session.execute(
                        insert(JobRow)
                        .values(
                            tenant_id=self.tenant,
                            job_id=uuid4(),
                            job_type=job_type,
                            idempotency_key=f"extract_event:{event_id}:{new_version}",
                            payload={"event_id": event_id, "extractor_version": new_version},
                            status="pending",
                            attempts=0,
                            max_attempts=5,
                            available_at=now,
                            created_at=now,
                            updated_at=now,
                        )
                        .on_conflict_do_nothing(
                            index_elements=["tenant_id", "job_type", "idempotency_key"]
                        )
                    )
                    row.status, row.last_error_code = "dead", "EXTRACTOR_MIGRATED"
                else:
                    row.status, row.attempts, row.last_error_code = "pending", 0, None
                row.available_at, row.updated_at = now, now
                row.lease_owner, row.leased_until = None, None
            self._audit(session, "queue.requeue", len(rows), now)
            return len(rows)

    async def rebuild_model(self, model: str, key: str, *, limit: int = 1000) -> int:
        if not model or not key or not 1 <= limit <= 1000:
            raise ValueError("model/key and bounded limit required")
        async with session_for_principal(self.sessions, self.principal) as session:
            versions = await session.scalars(
                select(MemoryVersionRow.memory_version_id)
                .join(
                    MemoryEmbeddingRow,
                    (MemoryEmbeddingRow.tenant_id == MemoryVersionRow.tenant_id)
                    & (MemoryEmbeddingRow.memory_version_id == MemoryVersionRow.memory_version_id),
                )
                .where(MemoryVersionRow.tenant_id == self.tenant, MemoryEmbeddingRow.model == model)
                .where(
                    ~select(JobRow.job_id)
                    .where(
                        JobRow.tenant_id == self.tenant,
                        JobRow.job_type == "embed_memory",
                        JobRow.idempotency_key
                        == func.concat(
                            "model-rebuild:", MemoryVersionRow.memory_version_id, ":", key
                        ),
                    )
                    .exists()
                )
                .order_by(MemoryVersionRow.memory_version_id)
                .limit(limit)
            )
            now = datetime.now(UTC)
            count = 0
            for version in versions:
                result = await session.execute(
                    insert(JobRow)
                    .values(
                        tenant_id=self.tenant,
                        job_id=uuid4(),
                        job_type="embed_memory",
                        idempotency_key=f"model-rebuild:{version}:{key}",
                        payload={"version_id": str(version)},
                        status="pending",
                        attempts=0,
                        max_attempts=5,
                        available_at=now,
                        created_at=now,
                        updated_at=now,
                    )
                    .on_conflict_do_nothing(
                        index_elements=["tenant_id", "job_type", "idempotency_key"]
                    )
                    .returning(JobRow.job_id)
                )
                count += result.scalar_one_or_none() is not None
            self._audit(session, "queue.rebuild_model", count, now)
            return count

    async def cleanup_idempotency(self, *, limit: int = 1000) -> int:
        if not 1 <= limit <= 1000:
            raise ValueError("limit must be 1..1000")
        async with session_for_principal(self.sessions, self.principal) as session:
            now = datetime.now(UTC)
            # Advisory locks match writers; lock expiry deletion and replay atomically.
            keys = list(
                await session.scalars(
                    select(IdempotencyRecordRow.idempotency_key)
                    .where(
                        IdempotencyRecordRow.tenant_id == self.tenant,
                        IdempotencyRecordRow.created_at <= now - timedelta(days=7),
                    )
                    .order_by(IdempotencyRecordRow.created_at)
                    .limit(limit)
                )
            )
            from agent_memory.infrastructure.repositories import PostgresIdempotencyRepository

            repo = PostgresIdempotencyRepository(session, lambda: now)
            count = 0
            for key in keys:
                await repo.lock(self.tenant, key)
                result = await session.execute(
                    delete(IdempotencyRecordRow)
                    .where(
                        IdempotencyRecordRow.tenant_id == self.tenant,
                        IdempotencyRecordRow.idempotency_key == key,
                        IdempotencyRecordRow.created_at <= now - timedelta(days=7),
                    )
                    .returning(IdempotencyRecordRow.idempotency_key)
                )
                count += result.scalar_one_or_none() is not None
            return count

    def _audit(self, session: AsyncSession, action: str, count: int, now: datetime) -> None:
        session.add(
            AuditLogRow(
                tenant_id=self.tenant,
                audit_id=uuid4(),
                actor_id=UUID(int=0),
                action=action,
                decision="allow",
                reason_code="ADMIN_BATCH",
                resource_id=None,
                metadata_json={"count": count},
                occurred_at=now,
            )
        )
