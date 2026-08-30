from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from agent_memory.application.event_commands import EventIngestionResult
from agent_memory.domain.events import EventDraft


@dataclass(frozen=True, slots=True)
class OutboxMessage:
    tenant_id: UUID
    outbox_id: UUID
    event_id: UUID
    topic: str
    created_at: datetime


class EventIngestionRepository(Protocol):
    async def ingest_batch(
        self,
        tenant_id: UUID,
        actor_user_id: UUID,
        drafts: tuple[EventDraft, ...],
    ) -> tuple[EventIngestionResult, ...]: ...


class OutboxDispatchRepository(Protocol):
    async def dispatch_once(
        self,
        tenant_id: UUID,
        batch_size: int,
        extractor_version: str,
    ) -> int: ...
