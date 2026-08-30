from collections.abc import Callable
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from agent_memory.application.event_commands import EventIngestionResult
from agent_memory.domain.errors import (
    EventIdempotencyConflict,
    EventSequenceConflict,
    LeaseLost,
)
from agent_memory.domain.events import EventDraft
from agent_memory.domain.jobs import Job, JobStatus
from agent_memory.infrastructure.orm import EventRow, JobRow, OutboxMessageRow


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


class PostgresOutboxRepository:
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

    async def dispatch_once(
        self,
        tenant_id: UUID,
        batch_size: int,
        extractor_version: str,
    ) -> int:
        now = self._now()
        messages = list(
            (
                await self._session.execute(
                    select(OutboxMessageRow)
                    .where(
                        OutboxMessageRow.tenant_id == tenant_id,
                        OutboxMessageRow.status == "pending",
                        OutboxMessageRow.available_at <= now,
                    )
                    .order_by(OutboxMessageRow.created_at, OutboxMessageRow.outbox_id)
                    .limit(batch_size)
                    .with_for_update(skip_locked=True)
                )
            ).scalars()
        )
        for message in messages:
            idempotency_key = (
                f"extract_event:{message.aggregate_id}:{extractor_version}"
            )
            await self._session.execute(
                insert(JobRow)
                .values(
                    tenant_id=tenant_id,
                    job_id=self._new_id(),
                    job_type="extract_event",
                    idempotency_key=idempotency_key,
                    payload={
                        "event_id": str(message.aggregate_id),
                        "extractor_version": extractor_version,
                    },
                    status=JobStatus.PENDING.value,
                    attempts=0,
                    max_attempts=5,
                    available_at=now,
                    leased_until=None,
                    lease_owner=None,
                    last_error_code=None,
                    created_at=now,
                    updated_at=now,
                )
                .on_conflict_do_nothing(
                    index_elements=["tenant_id", "job_type", "idempotency_key"]
                )
            )
            message.status = "published"
            message.attempts += 1
            message.published_at = now
        await self._session.flush()
        return len(messages)


class PostgresJobQueue:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def claim(
        self,
        tenant_id: UUID,
        worker_id: str,
        now: datetime,
        lease_duration: timedelta,
    ) -> Job | None:
        row = (
            await self._session.execute(
                select(JobRow)
                .where(
                    JobRow.tenant_id == tenant_id,
                    or_(
                        and_(
                            JobRow.status.in_(["pending", "retry_wait"]),
                            JobRow.available_at <= now,
                        ),
                        and_(
                            JobRow.status == "running",
                            JobRow.leased_until <= now,
                        ),
                    ),
                )
                .order_by(JobRow.available_at, JobRow.created_at, JobRow.job_id)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        claimed = self._to_domain(row).claim(worker_id, now, lease_duration)
        self._apply(row, claimed)
        await self._session.flush()
        return claimed

    async def renew(
        self,
        tenant_id: UUID,
        job_id: UUID,
        worker_id: str,
        now: datetime,
        lease_duration: timedelta,
    ) -> Job:
        row = await self._locked_row(tenant_id, job_id)
        renewed = self._to_domain(row).renew(worker_id, now, lease_duration)
        self._apply(row, renewed)
        await self._session.flush()
        return renewed

    async def succeed(
        self,
        tenant_id: UUID,
        job_id: UUID,
        worker_id: str,
        now: datetime,
    ) -> Job:
        row = await self._locked_row(tenant_id, job_id)
        succeeded = self._to_domain(row).succeed(worker_id, now)
        self._apply(row, succeeded)
        await self._session.flush()
        return succeeded

    async def fail(
        self,
        tenant_id: UUID,
        job_id: UUID,
        worker_id: str,
        now: datetime,
        error_code: str,
        *,
        retryable: bool,
    ) -> Job:
        row = await self._locked_row(tenant_id, job_id)
        failed = self._to_domain(row).fail(
            worker_id,
            now,
            error_code,
            retryable=retryable,
        )
        self._apply(row, failed)
        await self._session.flush()
        return failed

    async def _locked_row(self, tenant_id: UUID, job_id: UUID) -> JobRow:
        row = (
            await self._session.execute(
                select(JobRow)
                .where(JobRow.tenant_id == tenant_id, JobRow.job_id == job_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if row is None:
            raise LeaseLost(str(job_id))
        return row

    @staticmethod
    def _to_domain(row: JobRow) -> Job:
        return Job(
            tenant_id=row.tenant_id,
            job_id=row.job_id,
            job_type=row.job_type,
            idempotency_key=row.idempotency_key,
            payload=row.payload,
            status=JobStatus(row.status),
            attempts=row.attempts,
            max_attempts=row.max_attempts,
            available_at=row.available_at,
            leased_until=row.leased_until,
            lease_owner=row.lease_owner,
            last_error_code=row.last_error_code,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    @staticmethod
    def _apply(row: JobRow, job: Job) -> None:
        row.status = job.status.value
        row.attempts = job.attempts
        row.available_at = job.available_at
        row.leased_until = job.leased_until
        row.lease_owner = job.lease_owner
        row.last_error_code = job.last_error_code
        row.updated_at = job.updated_at
