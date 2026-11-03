from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from agent_memory.domain.events import EventDraft
from agent_memory.domain.jobs import JobPriority


@dataclass(frozen=True, slots=True)
class IngestEventBatchCommand:
    drafts: tuple[EventDraft, ...]
    # C4: interactive writes (an agent answering a user) outrank a backfill on the same queue.
    priority: int = int(JobPriority.INTERACTIVE)


@dataclass(frozen=True, slots=True)
class EventIngestionResult:
    event_id: UUID
    idempotency_key: str
    disposition: Literal["accepted", "duplicate"]
