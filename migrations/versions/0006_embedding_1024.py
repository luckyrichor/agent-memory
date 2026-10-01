"""Invalidate derived vectors and enqueue rebuilds when changing dimensions.

Run with migration privileges while API/workers are stopped. Memory versions
are preserved. Do not truncate/pad vectors from another model or dimension.
"""
from alembic import op

revision = "0006_embedding_1024"
down_revision = "0005_lexical_index"
branch_labels = None
depends_on = None


def resize(dimensions: int) -> None:
    op.execute("""DO $$ BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = current_user
                       AND (rolsuper OR rolbypassrls)) THEN
            RAISE EXCEPTION 'Dimension migration requires an administrator that can see all tenants';
        END IF;
    END $$""")
    op.execute("DELETE FROM memory_embeddings")
    op.execute(f"ALTER TABLE memory_embeddings ALTER COLUMN embedding TYPE vector({dimensions})")
    op.execute(f"""
        INSERT INTO jobs (tenant_id, job_id, job_type, idempotency_key, payload,
                          status, attempts, max_attempts, available_at, created_at, updated_at)
        SELECT tenant_id, gen_random_uuid(), 'embed_memory',
               'dimension-{dimensions}:' || memory_version_id::text,
               jsonb_build_object('version_id', memory_version_id::text),
               'pending', 0, 5, now(), now(), now()
        FROM memory_versions
        ON CONFLICT (tenant_id, job_type, idempotency_key) DO UPDATE
        SET status = 'pending', attempts = 0, available_at = now(), updated_at = now()
    """)


def upgrade() -> None:
    resize(1024)


def downgrade() -> None:
    resize(1536)
