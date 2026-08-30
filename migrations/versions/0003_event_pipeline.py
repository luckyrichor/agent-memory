"""Create the tenant-isolated event and extraction pipeline."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_event_pipeline"
down_revision: str | None = "0002_current_version_integrity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("events", "outbox_messages", "jobs", "evidence")
TENANT_POLICY = (
    "tenant_id = nullif(current_setting('app.current_tenant_id', true), '')::uuid"
)
SCOPE_CHECK = (
    "(scope_kind = 'tenant' AND workspace_id IS NULL AND subject_user_id IS NULL) OR "
    "(scope_kind = 'workspace' AND workspace_id IS NOT NULL AND subject_user_id IS NULL) OR "
    "(scope_kind = 'user_global' AND workspace_id IS NULL AND subject_user_id IS NOT NULL) OR "
    "(scope_kind = 'user_workspace' AND workspace_id IS NOT NULL "
    "AND subject_user_id IS NOT NULL)"
)


def upgrade() -> None:
    op.create_table(
        "events",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("session_id", sa.String(255), nullable=False),
        sa.Column("sequence_number", sa.BigInteger, nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("scope_kind", sa.String(32), nullable=False),
        sa.Column("workspace_id", sa.String(512)),
        sa.Column("subject_user_id", postgresql.UUID(as_uuid=True)),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_id", sa.String(255), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.CheckConstraint("sequence_number > 0", name="ck_events_positive_sequence"),
        sa.CheckConstraint(
            "event_type IN ('tool.result', 'task.completed', 'user.confirmed')",
            name="ck_events_type",
        ),
        sa.CheckConstraint(SCOPE_CHECK, name="ck_events_scope_shape"),
        sa.PrimaryKeyConstraint("tenant_id", "event_id", name="pk_events"),
        sa.UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name="uq_events_idempotency",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "session_id",
            "sequence_number",
            name="uq_events_session_sequence",
        ),
    )

    op.create_table(
        "outbox_messages",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("outbox_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("topic", sa.String(64), nullable=False),
        sa.Column("aggregate_type", sa.String(64), nullable=False),
        sa.Column("aggregate_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("status IN ('pending', 'published')", name="ck_outbox_status"),
        sa.CheckConstraint("attempts >= 0", name="ck_outbox_attempts"),
        sa.PrimaryKeyConstraint("tenant_id", "outbox_id", name="pk_outbox_messages"),
        sa.UniqueConstraint(
            "tenant_id",
            "topic",
            "aggregate_id",
            name="uq_outbox_aggregate",
        ),
    )
    op.create_index(
        "ix_outbox_claimable",
        "outbox_messages",
        ["tenant_id", "status", "available_at", "created_at"],
    )

    op.create_table(
        "jobs",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_type", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempts", sa.Integer, nullable=False),
        sa.Column("max_attempts", sa.Integer, nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("leased_until", sa.DateTime(timezone=True)),
        sa.Column("lease_owner", sa.String(255)),
        sa.Column("last_error_code", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'retry_wait', 'succeeded', 'dead')",
            name="ck_jobs_status",
        ),
        sa.CheckConstraint("attempts >= 0", name="ck_jobs_attempts"),
        sa.CheckConstraint("max_attempts > 0", name="ck_jobs_max_attempts"),
        sa.PrimaryKeyConstraint("tenant_id", "job_id", name="pk_jobs"),
        sa.UniqueConstraint(
            "tenant_id",
            "job_type",
            "idempotency_key",
            name="uq_jobs_idempotency",
        ),
    )
    op.create_index(
        "ix_jobs_claimable",
        "jobs",
        ["tenant_id", "status", "available_at", "created_at"],
    )
    op.create_index(
        "ix_jobs_expired_lease",
        "jobs",
        ["tenant_id", "status", "leased_until"],
    )

    op.create_table(
        "evidence",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("memory_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "role IN ('supports', 'contradicts', 'triggered_by', 'verified_by')",
            name="ck_evidence_role",
        ),
        sa.PrimaryKeyConstraint(
            "tenant_id",
            "memory_version_id",
            "event_id",
            "role",
            name="pk_evidence",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "memory_version_id"],
            ["memory_versions.tenant_id", "memory_versions.memory_version_id"],
            name="fk_evidence_memory_version",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            ["events.tenant_id", "events.event_id"],
            name="fk_evidence_event",
            ondelete="CASCADE",
        ),
    )

    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {table}_tenant_isolation ON {table} "
            f"USING ({TENANT_POLICY}) WITH CHECK ({TENANT_POLICY})"
        )
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO agent_memory_app")


def downgrade() -> None:
    op.drop_table("evidence")
    op.drop_table("jobs")
    op.drop_table("outbox_messages")
    op.drop_table("events")
