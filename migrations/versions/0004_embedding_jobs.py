"""Transactional embedding scheduling for every immutable memory version."""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0004_embedding_jobs"
down_revision: str | None = "0003_event_pipeline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "memory_embeddings",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("memory_version_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("model", sa.String(255), nullable=False),
        sa.Column("embedding", Vector(1536), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id", "memory_version_id"],
            ["memory_versions.tenant_id", "memory_versions.memory_version_id"], ondelete="CASCADE"),
    )
    table = "memory_embeddings"
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY {table}_tenant_isolation ON {table} "
               "USING (tenant_id = nullif(current_setting('app.current_tenant_id', true), '')::uuid) "
               "WITH CHECK (tenant_id = nullif(current_setting('app.current_tenant_id', true), '')::uuid)")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO agent_memory_app")
    # SECURITY INVOKER: trigger uses caller's RLS; no tenant privilege escalation.
    op.execute("""
        CREATE FUNCTION enqueue_memory_embedding() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          INSERT INTO jobs (tenant_id, job_id, job_type, idempotency_key, payload,
                            status, attempts, max_attempts, available_at, created_at, updated_at)
          VALUES (NEW.tenant_id, gen_random_uuid(), 'embed_memory',
                  NEW.memory_version_id::text,
                  jsonb_build_object('version_id', NEW.memory_version_id::text),
                  'pending', 0, 5, now(), now(), now())
          ON CONFLICT (tenant_id, job_type, idempotency_key) DO NOTHING;
          RETURN NEW;
        END $$;
        CREATE TRIGGER memory_embedding_job AFTER INSERT ON memory_versions
        FOR EACH ROW EXECUTE FUNCTION enqueue_memory_embedding();
    """)
    # Backfill existing versions: explicit tenant setting so FORCE RLS is respected.
    # Existing data can instead be rebuilt per tenant using the CLI.


def downgrade() -> None:
    op.execute("DROP TRIGGER memory_embedding_job ON memory_versions")
    op.execute("DROP FUNCTION enqueue_memory_embedding()")
    op.drop_table("memory_embeddings")
