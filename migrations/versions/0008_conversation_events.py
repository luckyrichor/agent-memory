"""Accept bounded untrusted conversation events without changing scope or RLS."""
from alembic import op

revision = '0008_conversation_events'
down_revision = '0007_review_hardening'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint('ck_events_type', 'events', type_='check')
    op.create_check_constraint('ck_events_type', 'events',
        "event_type IN ('tool.result', 'task.completed', 'user.confirmed', 'conversation.message')")


def downgrade() -> None:
    # Never silently delete conversation history to make rollback succeed.
    op.execute("""DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM events WHERE event_type='conversation.message') THEN
        RAISE EXCEPTION 'Conversation events exist; refusing lossy downgrade';
      END IF;
    END $$""")
    op.drop_constraint('ck_events_type', 'events', type_='check')
    op.create_check_constraint('ck_events_type', 'events',
        "event_type IN ('tool.result', 'task.completed', 'user.confirmed')")
