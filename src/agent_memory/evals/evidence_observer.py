"""Internal evaluation measurement: observe IDs only, under non-owner RLS.

Writes and searches still go through the SDK. This read-only exception measures
Event -> Evidence -> MemoryVersion lineage until a public evidence endpoint exists.
"""

from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from agent_memory.infrastructure.orm import EvidenceRow, MemoryVersionRow


async def observe_versions(
    session: AsyncSession, mapping: list[dict[str, Any]], *, tenant_id: UUID
) -> list[dict[str, Any]]:
    unsafe = await session.scalar(
        text("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = current_user")
    )
    owner = await session.scalar(
        text(
            "SELECT pg_has_role(current_user, relowner, 'USAGE') FROM pg_class "
            "WHERE oid = 'evidence'::regclass"
        )
    )
    if unsafe or owner:
        raise ValueError("evaluation evidence observer requires non-owner NOBYPASSRLS role")
    rows = []
    for item in mapping:
        event_id = item.get("event_id")
        if event_id is None:
            raise ValueError("full-mode evidence input must have event_id")
        matches = await session.execute(
            select(MemoryVersionRow.memory_id, EvidenceRow.memory_version_id)
            .join(
                EvidenceRow,
                (MemoryVersionRow.tenant_id == EvidenceRow.tenant_id)
                & (MemoryVersionRow.memory_version_id == EvidenceRow.memory_version_id),
            )
            .where(EvidenceRow.tenant_id == tenant_id, EvidenceRow.event_id == UUID(event_id))
        )
        for memory_id, version_id in matches:
            rows.append({**item, "memory_id": str(memory_id), "version_id": str(version_id)})
    return rows
