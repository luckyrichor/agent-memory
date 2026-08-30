from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from agent_memory.application.event_commands import EventIngestionResult
from agent_memory.domain.errors import EventIdempotencyConflict, EventSequenceConflict
from agent_memory.domain.events import EventDraft
from agent_memory.infrastructure.orm import EventRow, OutboxMessageRow


class PostgresEventIngestionRepository:
    def __init__(
        self,
        session: AsyncSession,
        *,
        new_id: Callable[[], UUID],
        now: Callable[[], datetime],
    ) -> None:
        self._session = session
        self._new_id = new_id
        self._now = now

    async def ingest_batch(
        self,
        tenant_id: UUID,
        actor_user_id: UUID,
        drafts: tuple[EventDraft, ...],
    ) -> tuple[EventIngestionResult, ...]:
        idempotency_keys = {draft.idempotency_key for draft in drafts}
        existing_rows = (
            await self._session.execute(
                select(EventRow).where(
                    EventRow.tenant_id == tenant_id,
                    EventRow.idempotency_key.in_(idempotency_keys),
                )
            )
        ).scalars()
        by_idempotency = {row.idempotency_key: row for row in existing_rows}

        sequence_predicates = [
            and_(
                EventRow.session_id == draft.session_id,
                EventRow.sequence_number == draft.sequence_number,
            )
            for draft in drafts
        ]
        by_sequence: dict[tuple[str, int], str] = {}
        if sequence_predicates:
            sequence_rows = (
                await self._session.execute(
                    select(EventRow).where(
                        EventRow.tenant_id == tenant_id,
                        or_(*sequence_predicates),
                    )
                )
            ).scalars()
            by_sequence = {
                (row.session_id, row.sequence_number): row.idempotency_key
                for row in sequence_rows
            }

        results: list[EventIngestionResult] = []
        new_rows: list[EventRow | OutboxMessageRow] = []
        for draft in drafts:
            request_hash = draft.request_hash()
            existing = by_idempotency.get(draft.idempotency_key)
            if existing is not None:
                if existing.request_hash != request_hash:
                    raise EventIdempotencyConflict(draft.idempotency_key)
                results.append(
                    EventIngestionResult(
                        existing.event_id,
                        draft.idempotency_key,
                        "duplicate",
                    )
                )
                continue

            sequence_key = (draft.session_id, draft.sequence_number)
            if sequence_key in by_sequence:
                raise EventSequenceConflict(f"{draft.session_id}:{draft.sequence_number}")

            event_id = self._new_id()
            received_at = self._now()
            event_row = EventRow(
                tenant_id=tenant_id,
                event_id=event_id,
                idempotency_key=draft.idempotency_key,
                request_hash=request_hash,
                session_id=draft.session_id,
                sequence_number=draft.sequence_number,
                event_type=draft.event_type.value,
                scope_kind=draft.scope.kind.value,
                workspace_id=draft.scope.workspace_id,
                subject_user_id=draft.scope.subject_user_id,
                actor_user_id=actor_user_id,
                agent_id=draft.agent_id,
                occurred_at=draft.occurred_at,
                received_at=received_at,
                payload=dict(draft.payload),
            )
            outbox_row = OutboxMessageRow(
                tenant_id=tenant_id,
                outbox_id=self._new_id(),
                topic="event.recorded",
                aggregate_type="event",
                aggregate_id=event_id,
                payload={"event_id": str(event_id)},
                status="pending",
                available_at=received_at,
                attempts=0,
                created_at=received_at,
                published_at=None,
            )
            by_idempotency[draft.idempotency_key] = event_row
            by_sequence[sequence_key] = draft.idempotency_key
            new_rows.extend((event_row, outbox_row))
            results.append(
                EventIngestionResult(event_id, draft.idempotency_key, "accepted")
            )

        self._session.add_all(new_rows)
        try:
            await self._session.flush()
        except IntegrityError as error:
            constraint = getattr(getattr(error.orig, "diag", None), "constraint_name", "")
            if constraint == "uq_events_idempotency":
                raise EventIdempotencyConflict("concurrent event replay") from error
            if constraint == "uq_events_session_sequence":
                raise EventSequenceConflict("concurrent sequence collision") from error
            raise
        return tuple(results)
