"""Create the tenant-isolated memory foundation schema."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_memory_foundation"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("memories", "memory_versions", "idempotency_records", "audit_logs")
TENANT_POLICY = (
    "tenant_id = "
    "nullif(current_setting('app.current_tenant_id', true), '')::uuid"
)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute(
        "DO $$ BEGIN "
        "IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'agent_memory_app') THEN "
        "CREATE ROLE agent_memory_app NOLOGIN NOSUPERUSER NOBYPASSRLS; "
        "END IF; END $$"
    )

    op.create_table(
        "memories",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("memory_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("memory_type", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("scope_kind", sa.String(32), nullable=False),
        sa.Column("workspace_id", sa.String(512)),
        sa.Column("subject_user_id", postgresql.UUID(as_uuid=True)),
        sa.Column("visibility", sa.String(32), nullable=False, server_default="scope"),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("current_version_id", postgresql.UUID(as_uuid=True)),
        sa.Column("revision", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("disabled_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "memory_type IN ('episodic', 'semantic', 'procedural')",
            name="ck_memories_type",
        ),
        sa.CheckConstraint(
            "status IN ('candidate', 'needs_review', 'active', 'rejected', "
            "'superseded', 'invalidated', 'archived', 'deleted')",
            name="ck_memories_status",
        ),
        sa.CheckConstraint(
            "(scope_kind = 'tenant' AND workspace_id IS NULL AND subject_user_id IS NULL) OR "
            "(scope_kind = 'workspace' AND workspace_id IS NOT NULL "
            "AND subject_user_id IS NULL) OR "
            "(scope_kind = 'user_global' AND workspace_id IS NULL "
            "AND subject_user_id IS NOT NULL) OR "
            "(scope_kind = 'user_workspace' AND workspace_id IS NOT NULL "
            "AND subject_user_id IS NOT NULL)",
            name="ck_memories_scope_shape",
        ),
        sa.PrimaryKeyConstraint("tenant_id", "memory_id", name="pk_memories"),
    )

    op.create_table(
        "memory_versions",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("memory_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("memory_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_number", sa.Integer, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("structured_content", postgresql.JSONB, nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column("utility", sa.Float, nullable=False),
        sa.Column("authority_level", sa.SmallInteger, nullable=False),
        sa.Column("verification_status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint(
            "tenant_id",
            "memory_version_id",
            name="pk_memory_versions",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "memory_id"],
            ["memories.tenant_id", "memories.memory_id"],
            name="fk_memory_versions_memory",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "memory_id",
            "version_number",
            name="uq_memory_versions_number",
        ),
    )

    op.create_foreign_key(
        "fk_memories_current_version",
        "memories",
        "memory_versions",
        ["tenant_id", "current_version_id"],
        ["tenant_id", "memory_version_id"],
        deferrable=True,
        initially="DEFERRED",
        use_alter=True,
    )

    op.create_table(
        "idempotency_records",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("result_json", postgresql.JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint(
            "tenant_id",
            "idempotency_key",
            name="pk_idempotency_records",
        ),
    )

    op.create_table(
        "audit_logs",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("audit_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("reason_code", sa.String(64), nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True)),
        sa.Column("metadata_json", postgresql.JSONB, nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "audit_id", name="pk_audit_logs"),
    )

    op.create_index("ix_memories_tenant_status", "memories", ["tenant_id", "status"])
    op.create_index(
        "ix_memories_tenant_workspace_status",
        "memories",
        ["tenant_id", "workspace_id", "status"],
    )
    op.create_index(
        "ix_memories_tenant_user_status",
        "memories",
        ["tenant_id", "subject_user_id", "status"],
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
    op.drop_table("audit_logs")
    op.drop_table("idempotency_records")
    op.drop_constraint("fk_memories_current_version", "memories", type_="foreignkey")
    op.drop_table("memory_versions")
    op.drop_table("memories")
