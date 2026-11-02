"""Wake workers on new jobs/outbox rows (LISTEN/NOTIFY); polling stays as the safety net.

The notification payload is md5(tenant_id), never the tenant id or any content: a worker only
needs to learn "something new for my tenant", and the claim itself is still decided by row state,
lease and RLS. A lost or duplicated notification therefore cannot change correctness, only latency.
"""
from alembic import op

revision = "0009_job_notify"
down_revision = "0008_conversation_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for channel, table, trigger in (
        ("agent_memory_jobs", "jobs", "jobs_notify"),
        ("agent_memory_outbox", "outbox_messages", "outbox_notify"),
    ):
        op.execute(f"""
            CREATE FUNCTION {trigger}_fn() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
              PERFORM pg_notify('{channel}', md5(NEW.tenant_id::text));
              RETURN NULL;
            END $$;
            CREATE TRIGGER {trigger} AFTER INSERT ON {table}
            FOR EACH ROW EXECUTE FUNCTION {trigger}_fn();
        """)


def downgrade() -> None:
    op.execute("DROP TRIGGER outbox_notify ON outbox_messages")
    op.execute("DROP FUNCTION outbox_notify_fn()")
    op.execute("DROP TRIGGER jobs_notify ON jobs")
    op.execute("DROP FUNCTION jobs_notify_fn()")
