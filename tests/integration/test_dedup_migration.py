"""Migration 0012: dedup_hash is added, backfilled for existing rows, and skipped for purged ones."""

from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from testcontainers.community.postgres import PostgresContainer

from agent_memory.domain.dedup import dedup_hash


def test_backfill_hashes_existing_versions_and_skips_purged_ones():
    with PostgresContainer('pgvector/pgvector:pg16', driver='psycopg') as postgres:
        config = Config('alembic.ini')
        config.set_main_option('sqlalchemy.url', postgres.get_connection_url())
        command.upgrade(config, '0011_content_hash_index')
        engine = create_engine(postgres.get_connection_url())
        tenant, owner = uuid4(), uuid4()
        live, purged = (uuid4(), uuid4()), (uuid4(), uuid4())
        try:
            with engine.begin() as connection:
                connection.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"),
                                   {'t': str(tenant)})
                for memory_id, version_id, content, content_hash in (
                    (live[0], live[1], '  Use   UV for builds ', 'a' * 64),
                    (purged[0], purged[1], '', '0' * 64),
                ):
                    connection.execute(text("""INSERT INTO memories (tenant_id,memory_id,memory_type,
                        status,scope_kind,visibility,owner_user_id,revision,created_at,updated_at)
                        VALUES (:t,:m,'semantic','deleted','tenant','scope',:o,1,now(),now())"""),
                        {'t': tenant, 'm': memory_id, 'o': owner})
                    connection.execute(text("""INSERT INTO memory_versions (tenant_id,
                        memory_version_id,memory_id,version_number,content,structured_content,
                        content_hash,confidence,utility,authority_level,verification_status,
                        created_at) VALUES (:t,:v,:m,1,:c,'{}',:h,0.5,0.5,1,'unverified',now())"""),
                        {'t': tenant, 'v': version_id, 'm': memory_id, 'c': content, 'h': content_hash})
                    connection.execute(text("""UPDATE memories SET current_version_id = :v
                        WHERE tenant_id = :t AND memory_id = :m"""),
                        {'t': tenant, 'v': version_id, 'm': memory_id})
            command.upgrade(config, 'head')
            with engine.begin() as connection:
                connection.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"),
                                   {'t': str(tenant)})
                hashes = dict(connection.execute(text(
                    "SELECT memory_version_id, dedup_hash FROM memory_versions")).all())
            assert hashes[live[1]] == dedup_hash('use uv for builds')
            assert hashes[purged[1]] is None
            command.downgrade(config, '0011_content_hash_index')
            command.upgrade(config, 'head')
        finally:
            engine.dispose()
