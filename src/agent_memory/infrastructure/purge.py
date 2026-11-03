"""Physical clean-up of logically deleted memories (D3 / LC7).

``POST /v1/deletion-requests`` only flips the memory to ``deleted`` and answers
``pending_physical_cleanup``: the version rows still hold the original text, the derived
lexical vectors and the embedding vector. This module executes that clean-up.

What is erased, per version of a deleted memory:

* ``memory_versions.content`` -> empty string, ``structured_content`` -> ``{}``,
  ``reason`` -> NULL. The stored lexical vectors are generated from ``content`` and therefore
  collapse with it. Version rows themselves stay: lineage, audit and foreign keys point at them.
* ``content_hash`` -> a fixed marker (also the "already purged" flag) and ``dedup_hash`` -> NULL,
  because a hash of the text lets anyone holding a guess confirm it.
* ``memory_embeddings`` rows -> deleted (a vector is derived from the text).
* unfinished ``embed_memory`` jobs for those versions -> ``dead`` (``MEMORY_PURGED``), so a worker
  cannot recreate a vector from the now-empty text.

What this does NOT do, and must not be described as doing:

* it does not touch source ``events`` / ``evidence`` (the raw text the memory was extracted from
  has its own retention question),
* it does not remove anything from WAL, replicas, backups or dead tuples not yet vacuumed,
* it does not remove the memory row, its status, ids, timestamps or audit trail.

Default is a dry run; nothing is written unless ``execute=True``. The function only ever sees one
tenant: RLS is the safety net, the explicit tenant filter is the first line.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agent_memory.domain.enums import MemoryStatus
from agent_memory.domain.principal import RequestPrincipal
from agent_memory.infrastructure.db import session_for_principal
from agent_memory.infrastructure.orm import (
    AuditLogRow,
    JobRow,
    MemoryEmbeddingRow,
    MemoryRow,
    MemoryVersionRow,
)

PURGED_CONTENT_HASH = "0" * 64
PURGE_ACTOR_ID = UUID(int=0xD3)
UNFINISHED_JOB_STATUSES = ("pending", "running", "retry_wait")


@dataclass(frozen=True)
class PurgeReport:
    executed: bool
    memories: int
    versions: int
    embeddings: int
    jobs_stopped: int


def _principal(tenant_id: UUID) -> RequestPrincipal:
    return RequestPrincipal(
        tenant_id, PURGE_ACTOR_ID, frozenset(), frozenset({"memory:delete"}), frozenset()
    )


async def _eligible_versions(
    session: AsyncSession, tenant_id: UUID, cutoff: datetime, limit: int
) -> list[tuple[UUID, UUID]]:
    """(memory_id, version_id) of un-purged versions of deleted memories older than the cutoff."""
    eligible_memories = (
        select(MemoryRow.memory_id)
        .where(
            MemoryRow.tenant_id == tenant_id,
            MemoryRow.status == MemoryStatus.DELETED.value,
            MemoryRow.updated_at <= cutoff,
        )
        .order_by(MemoryRow.memory_id)
        .limit(limit)
    )
    rows = await session.execute(
        select(MemoryVersionRow.memory_id, MemoryVersionRow.memory_version_id).where(
            MemoryVersionRow.tenant_id == tenant_id,
            MemoryVersionRow.memory_id.in_(eligible_memories),
            MemoryVersionRow.content_hash != PURGED_CONTENT_HASH,
        )
    )
    return [(memory_id, version_id) for memory_id, version_id in rows.all()]


async def purge_deleted_memories(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: UUID,
    *,
    older_than: timedelta,
    now: datetime,
    new_id: Callable[[], UUID],
    execute: bool = False,
    limit: int = 1000,
) -> PurgeReport:
    """Purge (or, by default, only count) one batch of up to ``limit`` deleted memories.

    Idempotent: versions already purged are skipped, so a repeat run reports zeros.
    One transaction per call: either the whole batch is purged or none of it.
    """
    if limit < 1:
        raise ValueError("limit must be positive")
    async with session_for_principal(sessions, _principal(tenant_id)) as session:
        pairs = await _eligible_versions(session, tenant_id, now - older_than, limit)
        version_ids = [version_id for _, version_id in pairs]
        memory_ids = sorted({memory_id for memory_id, _ in pairs})
        if not version_ids:
            return PurgeReport(execute, 0, 0, 0, 0)

        embeddings = int(
            await session.scalar(
                select(func.count())
                .select_from(MemoryEmbeddingRow)
                .where(
                    MemoryEmbeddingRow.tenant_id == tenant_id,
                    MemoryEmbeddingRow.memory_version_id.in_(version_ids),
                )
            )
            or 0
        )
        job_filter = (
            JobRow.tenant_id == tenant_id,
            JobRow.job_type == "embed_memory",
            JobRow.status.in_(UNFINISHED_JOB_STATUSES),
            JobRow.payload["version_id"].astext.in_([str(v) for v in version_ids]),
        )
        jobs_stopped = int(
            await session.scalar(select(func.count()).select_from(JobRow).where(*job_filter)) or 0
        )
        report = PurgeReport(execute, len(memory_ids), len(version_ids), embeddings, jobs_stopped)
        if not execute:
            return report

        await session.execute(
            delete(MemoryEmbeddingRow).where(
                MemoryEmbeddingRow.tenant_id == tenant_id,
                MemoryEmbeddingRow.memory_version_id.in_(version_ids),
            )
        )
        await session.execute(
            update(JobRow)
            .where(*job_filter)
            .values(
                status="dead",
                last_error_code="MEMORY_PURGED",
                lease_owner=None,
                leased_until=None,
                updated_at=now,
            )
            .execution_options(synchronize_session=False)
        )
        await session.execute(
            update(MemoryVersionRow)
            .where(
                MemoryVersionRow.tenant_id == tenant_id,
                MemoryVersionRow.memory_version_id.in_(version_ids),
            )
            .values(
                content="",
                structured_content={},
                content_hash=PURGED_CONTENT_HASH,
                dedup_hash=None,
                reason=None,
            )
            .execution_options(synchronize_session=False)
        )
        for memory_id in memory_ids:
            session.add(
                AuditLogRow(
                    tenant_id=tenant_id,
                    audit_id=new_id(),
                    actor_id=PURGE_ACTOR_ID,
                    action="memory.purge",
                    decision="allow",
                    reason_code="MEMORY_PURGED",
                    resource_id=memory_id,
                    metadata_json={},
                    occurred_at=now,
                )
            )
        await session.flush()
        return report
