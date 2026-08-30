from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKeyConstraint,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class MemoryRow(Base):
    __tablename__ = "memories"
    __table_args__ = (
        CheckConstraint(
            "(scope_kind = 'tenant' AND workspace_id IS NULL AND subject_user_id IS NULL) OR "
            "(scope_kind = 'workspace' AND workspace_id IS NOT NULL "
            "AND subject_user_id IS NULL) OR "
            "(scope_kind = 'user_global' AND workspace_id IS NULL "
            "AND subject_user_id IS NOT NULL) OR "
            "(scope_kind = 'user_workspace' AND workspace_id IS NOT NULL "
            "AND subject_user_id IS NOT NULL)",
            name="ck_memories_scope_shape",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "memory_id", "current_version_id"],
            [
                "memory_versions.tenant_id",
                "memory_versions.memory_id",
                "memory_versions.memory_version_id",
            ],
            name="fk_memories_current_version",
            deferrable=True,
            initially="DEFERRED",
            use_alter=True,
        ),
        Index("ix_memories_tenant_status", "tenant_id", "status"),
        Index(
            "ix_memories_tenant_workspace_status",
            "tenant_id",
            "workspace_id",
            "status",
        ),
        Index(
            "ix_memories_tenant_user_status",
            "tenant_id",
            "subject_user_id",
            "status",
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    memory_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    memory_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    scope_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    workspace_id: Mapped[str | None] = mapped_column(String(512))
    subject_user_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    visibility: Mapped[str] = mapped_column(String(32), nullable=False, default="scope")
    owner_user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    current_version_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MemoryVersionRow(Base):
    __tablename__ = "memory_versions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "memory_id"],
            ["memories.tenant_id", "memories.memory_id"],
            name="fk_memory_versions_memory",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "tenant_id",
            "memory_id",
            "version_number",
            name="uq_memory_versions_number",
        ),
        UniqueConstraint(
            "tenant_id",
            "memory_id",
            "memory_version_id",
            name="uq_memory_versions_identity",
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    memory_version_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    memory_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    structured_content: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    utility: Mapped[float] = mapped_column(Float, nullable=False)
    authority_level: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    verification_status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class IdempotencyRecordRow(Base):
    __tablename__ = "idempotency_records"

    tenant_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(255), primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    result_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AuditLogRow(Base):
    __tablename__ = "audit_logs"

    tenant_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    audit_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    actor_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class EventRow(Base):
    __tablename__ = "events"
    __table_args__ = (
        CheckConstraint("sequence_number > 0", name="ck_events_positive_sequence"),
        CheckConstraint(
            "event_type IN ('tool.result', 'task.completed', 'user.confirmed')",
            name="ck_events_type",
        ),
        CheckConstraint(
            "(scope_kind = 'tenant' AND workspace_id IS NULL AND subject_user_id IS NULL) OR "
            "(scope_kind = 'workspace' AND workspace_id IS NOT NULL "
            "AND subject_user_id IS NULL) OR "
            "(scope_kind = 'user_global' AND workspace_id IS NULL "
            "AND subject_user_id IS NOT NULL) OR "
            "(scope_kind = 'user_workspace' AND workspace_id IS NOT NULL "
            "AND subject_user_id IS NOT NULL)",
            name="ck_events_scope_shape",
        ),
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_events_idempotency"),
        UniqueConstraint(
            "tenant_id",
            "session_id",
            "sequence_number",
            name="uq_events_session_sequence",
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    event_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    session_id: Mapped[str] = mapped_column(String(255), nullable=False)
    sequence_number: Mapped[int] = mapped_column(BigInteger, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    scope_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    workspace_id: Mapped[str | None] = mapped_column(String(512))
    subject_user_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    actor_user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    agent_id: Mapped[str] = mapped_column(String(255), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class OutboxMessageRow(Base):
    __tablename__ = "outbox_messages"
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'published')", name="ck_outbox_status"),
        CheckConstraint("attempts >= 0", name="ck_outbox_attempts"),
        UniqueConstraint(
            "tenant_id", "topic", "aggregate_id", name="uq_outbox_aggregate"
        ),
        Index(
            "ix_outbox_claimable",
            "tenant_id",
            "status",
            "available_at",
            "created_at",
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    outbox_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    topic: Mapped[str] = mapped_column(String(64), nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(64), nullable=False)
    aggregate_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class JobRow(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'retry_wait', 'succeeded', 'dead')",
            name="ck_jobs_status",
        ),
        CheckConstraint("attempts >= 0", name="ck_jobs_attempts"),
        CheckConstraint("max_attempts > 0", name="ck_jobs_max_attempts"),
        UniqueConstraint(
            "tenant_id", "job_type", "idempotency_key", name="uq_jobs_idempotency"
        ),
        Index(
            "ix_jobs_claimable",
            "tenant_id",
            "status",
            "available_at",
            "created_at",
        ),
        Index("ix_jobs_expired_lease", "tenant_id", "status", "leased_until"),
    )

    tenant_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    job_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    job_type: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    leased_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_owner: Mapped[str | None] = mapped_column(String(255))
    last_error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class EvidenceRow(Base):
    __tablename__ = "evidence"
    __table_args__ = (
        CheckConstraint(
            "role IN ('supports', 'contradicts', 'triggered_by', 'verified_by')",
            name="ck_evidence_role",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "memory_version_id"],
            ["memory_versions.tenant_id", "memory_versions.memory_version_id"],
            name="fk_evidence_memory_version",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            ["events.tenant_id", "events.event_id"],
            name="fk_evidence_event",
            ondelete="CASCADE",
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    memory_version_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    event_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    role: Mapped[str] = mapped_column(String(32), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
