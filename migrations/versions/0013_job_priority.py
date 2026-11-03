"""Job priority so interactive writes do not queue behind a bulk import (C4).

Adds ``jobs.priority`` (higher runs first inside one job type), the index the claim query needs,
and a replacement for the embedding trigger so the ``embed_memory`` job an extracted version
creates inherits the priority of the ``extract_event`` job that produced it.

The outbox -> job hop carries the priority in the outbox payload; the version -> embedding hop
carries it in the transaction-local ``app.job_priority`` setting, because the trigger has no other
way to see it. Both default to 0, so anything that does not set a priority keeps the old order.
"""
import sqlalchemy as sa
from alembic import op

revision = "0013_job_priority"
down_revision = "0012_dedup_hash"
branch_labels = None
depends_on = None


ENQUEUE_EMBEDDING = """
    CREATE OR REPLACE FUNCTION enqueue_memory_embedding() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      INSERT INTO jobs (tenant_id, job_id, job_type, idempotency_key, payload,
                        status, attempts, max_attempts, priority, available_at, created_at,
                        updated_at)
      VALUES (NEW.tenant_id, gen_random_uuid(), 'embed_memory',
              NEW.memory_version_id::text,
              jsonb_build_object('version_id', NEW.memory_version_id::text),
              'pending', 0, 5,
              COALESCE(nullif(current_setting('app.job_priority', true), '')::int, 0),
              now(), now(), now())
      ON CONFLICT (tenant_id, job_type, idempotency_key) DO NOTHING;
      RETURN NEW;
    END $$;
"""

OLD_ENQUEUE_EMBEDDING = """
    CREATE OR REPLACE FUNCTION enqueue_memory_embedding() RETURNS trigger LANGUAGE plpgsql AS $$
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
"""


def upgrade() -> None:
    op.add_column(
        "jobs", sa.Column("priority", sa.Integer(), nullable=False, server_default="0")
    )
    # Order matches the claim query: equality on tenant + type, then priority DESC, then FIFO.
    op.execute(
        "CREATE INDEX ix_jobs_claim_order ON jobs "
        "(tenant_id, job_type, priority DESC, available_at, created_at, job_id)"
    )
    op.execute(ENQUEUE_EMBEDDING)


def downgrade() -> None:
    op.execute(OLD_ENQUEUE_EMBEDDING)
    op.drop_index("ix_jobs_claim_order", table_name="jobs")
    op.drop_column("jobs", "priority")
