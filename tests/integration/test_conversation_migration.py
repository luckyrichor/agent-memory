from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import ProgrammingError
from testcontainers.community.postgres import PostgresContainer


def test_conversation_rollback_refuses_data_loss_and_preserves_rls():
    with PostgresContainer('pgvector/pgvector:pg16', driver='psycopg') as postgres:
        config = Config('alembic.ini')
        config.set_main_option('sqlalchemy.url', postgres.get_connection_url())
        command.upgrade(config, 'head')
        engine = create_engine(postgres.get_connection_url())
        try:
            with engine.begin() as connection:
                connection.execute(text("""INSERT INTO events (tenant_id,event_id,idempotency_key,
                    request_hash,session_id,sequence_number,event_type,scope_kind,actor_user_id,
                    agent_id,occurred_at,received_at,payload)
                    VALUES (:tenant,:event,'fixture',repeat('a',64),'fixture',1,
                    'conversation.message','tenant',:actor,'fixture',now(),now(),'{}')"""),
                    {'tenant':uuid4(),'event':uuid4(),'actor':uuid4()})
            with pytest.raises(ProgrammingError, match='refusing lossy downgrade'):
                command.downgrade(config, '0007_review_hardening')
            with engine.begin() as connection:
                assert connection.scalar(text("SELECT count(*) FROM events")) == 1
                assert connection.scalar(text("SELECT version_num FROM alembic_version")) == '0008_conversation_events'
                rls = connection.execute(text("SELECT relrowsecurity,relforcerowsecurity "
                                              "FROM pg_class WHERE relname='events'" )).one()
                assert all(rls)
                # This is synthetic isolated fixture cleanup, not a production rollback.
                connection.execute(text('DELETE FROM events'))
            command.downgrade(config, '0007_review_hardening')
            command.upgrade(config, 'head')
        finally:
            engine.dispose()
