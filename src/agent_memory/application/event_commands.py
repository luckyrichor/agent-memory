from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from agent_memory.domain.events import EventDraft


@dataclass(frozen=True, slots=True)
class IngestEventBatchCommand:
    drafts: tuple[EventDraft, ...]


@dataclass(frozen=True, slots=True)
class EventIngestionResult:
    event_id: UUID
    idempotency_key: str
    disposition: Literal["accepted", "duplicate"]
