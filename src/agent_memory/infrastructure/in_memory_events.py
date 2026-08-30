from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from agent_memory.application.event_commands import EventIngestionResult
from agent_memory.application.event_ports import OutboxMessage
from agent_memory.domain.errors import EventIdempotencyConflict, EventSequenceConflict
from agent_memory.domain.events import Event, EventDraft
from agent_memory.domain.jobs import Job, JobStatus


class InMemoryEventIngestionRepository:
    def __init__(
        self,
        *,
        new_id: Callable[[], UUID],
        now: Callable[[], datetime],
    ) -> None:
        self._new_id = new_id
        self._now = now
        self._events: dict[tuple[UUID, str], tuple[Event, str]] = {}
        self._sequences: dict[tuple[UUID, str, int], str] = {}
        self._outbox: list[OutboxMessage] = []
        self._published_outbox_ids: set[UUID] = set()
        self._jobs: dict[tuple[UUID, str, str], Job] = {}

    @property
    def event_count(self) -> int:
        return len(self._events)

    @property
    def outbox_count(self) -> int:
        return len(self._outbox)

    @property
    def job_count(self) -> int:
        return len(self._jobs)

    @property
    def outbox_status(self) -> str:
        return (
            "published"
            if self._outbox
            and all(item.outbox_id in self._published_outbox_ids for item in self._outbox)
            else "pending"
        )

    async def ingest_batch(
        self,
        tenant_id: UUID,
        actor_user_id: UUID,
        drafts: tuple[EventDraft, ...],
    ) -> tuple[EventIngestionResult, ...]:
        staged_events = dict(self._events)
        staged_sequences = dict(self._sequences)
        staged_outbox = list(self._outbox)
        results: list[EventIngestionResult] = []

        for draft in drafts:
            event_key = (tenant_id, draft.idempotency_key)
            request_hash = draft.request_hash()
            existing = staged_events.get(event_key)
            if existing is not None:
                event, existing_hash = existing
                if existing_hash != request_hash:
                    raise EventIdempotencyConflict(draft.idempotency_key)
                results.append(
                    EventIngestionResult(
                        event.event_id,
                        draft.idempotency_key,
                        "duplicate",
                    )
                )
                continue

            sequence_key = (tenant_id, draft.session_id, draft.sequence_number)
            existing_sequence_key = staged_sequences.get(sequence_key)
            if existing_sequence_key is not None:
                raise EventSequenceConflict(
                    f"{draft.session_id}:{draft.sequence_number}"
                )

            event = Event(
                tenant_id=tenant_id,
                event_id=self._new_id(),
                draft=draft,
                actor_user_id=actor_user_id,
                received_at=self._now(),
            )
            outbox = OutboxMessage(
                tenant_id=tenant_id,
                outbox_id=self._new_id(),
                event_id=event.event_id,
                topic="event.recorded",
                created_at=self._now(),
            )
            staged_events[event_key] = (event, request_hash)
            staged_sequences[sequence_key] = draft.idempotency_key
            staged_outbox.append(outbox)
            results.append(
                EventIngestionResult(event.event_id, draft.idempotency_key, "accepted")
            )

        self._events = staged_events
        self._sequences = staged_sequences
        self._outbox = staged_outbox
        return tuple(results)

    async def dispatch_once(
        self,
        tenant_id: UUID,
        batch_size: int,
        extractor_version: str,
    ) -> int:
        pending = [
            message
            for message in self._outbox
            if message.tenant_id == tenant_id
            and message.outbox_id not in self._published_outbox_ids
        ][:batch_size]
        for message in pending:
            idempotency_key = f"extract_event:{message.event_id}:{extractor_version}"
            job_key = (tenant_id, "extract_event", idempotency_key)
            if job_key not in self._jobs:
                self._jobs[job_key] = Job(
                    tenant_id=tenant_id,
                    job_id=self._new_id(),
                    job_type="extract_event",
                    idempotency_key=idempotency_key,
                    payload={
                        "event_id": str(message.event_id),
                        "extractor_version": extractor_version,
                    },
                    status=JobStatus.PENDING,
                    attempts=0,
                    max_attempts=5,
                    available_at=self._now(),
                    leased_until=None,
                    lease_owner=None,
                    last_error_code=None,
                    created_at=self._now(),
                    updated_at=self._now(),
                )
            self._published_outbox_ids.add(message.outbox_id)
        return len(pending)
