from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from testcontainers.community.postgres import PostgresContainer


def test_dimension_migration_preserves_versions_and_requeues_old_embeddings() -> None:
    with PostgresContainer("pgvector/pgvector:pg16", driver="psycopg") as postgres:
        config = Config("alembic.ini")
        config.set_main_option("sqlalchemy.url", postgres.get_connection_url())
        command.upgrade(config, "0005_lexical_index")
        engine = create_engine(postgres.get_connection_url())
        with engine.begin() as connection:
            for _ in range(2):
                ids = {"t": uuid4(), "m": uuid4(), "v": uuid4(), "u": uuid4()}
                connection.execute(text("INSERT INTO memories (tenant_id, memory_id, "
                    "memory_type, status, scope_kind, visibility, owner_user_id, current_version_id, "
                    "revision, created_at, updated_at) VALUES (:t,:m,'semantic','active','tenant',"
                    "'scope',:u,:v,1,now(),now())"), ids)
                connection.execute(text("INSERT INTO memory_versions (tenant_id, memory_version_id,"
                    "memory_id,version_number,content,structured_content,content_hash,confidence,"
                    "utility,authority_level,verification_status,created_at) VALUES "
                    "(:t,:v,:m,1,'preserved','{}',repeat('a',64),1,1,1,'unverified',now())"), ids)
                connection.execute(text("INSERT INTO memory_embeddings "
                    "VALUES (:t,:v,'old-model',CAST(:vec AS vector),now())"),
                    {**ids, "vec": "[" + ",".join(["1"]*1536) + "]"})
            connection.execute(text("UPDATE jobs SET status='succeeded'"))
            assert connection.scalar(text("SELECT format_type(atttypid, atttypmod) "
                "FROM pg_attribute WHERE attrelid='memory_embeddings'::regclass "
                "AND attname='embedding'")) == "vector(1536)"
        command.upgrade(config, "head")
        with engine.begin() as connection:
            assert connection.scalar(text("SELECT count(*) FROM memory_versions "
                "WHERE content='preserved'")) == 2
            assert connection.scalar(text("SELECT count(*) FROM memory_embeddings")) == 0
            assert connection.scalar(text("SELECT count(*) FROM jobs WHERE status='pending' "
                "AND idempotency_key LIKE 'dimension-1024:%'")) == 2
            assert connection.scalar(text("SELECT format_type(atttypid, atttypmod) "
                "FROM pg_attribute WHERE attrelid='memory_embeddings'::regclass "
                "AND attname='embedding'")) == "vector(1024)"
        engine.dispose()
