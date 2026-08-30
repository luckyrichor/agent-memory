from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from agent_memory.application.event_commands import EventIngestionResult
from agent_memory.application.event_ports import OutboxMessage
from agent_memory.domain.errors import EventIdempotencyConflict, EventSequenceConflict
from agent_memory.domain.events import Event, EventDraft


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

    @property
    def event_count(self) -> int:
        return len(self._events)

    @property
    def outbox_count(self) -> int:
        return len(self._outbox)

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
