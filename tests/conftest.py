from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from testcontainers.community.postgres import PostgresContainer


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    with PostgresContainer(
        "pgvector/pgvector:pg16",
        username="agent_memory",
        password="integration-only",
        dbname="agent_memory",
        driver="psycopg",
    ) as postgres:
        yield postgres.get_connection_url()


@pytest.fixture(scope="session")
def app_database_url(database_url: str) -> str:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")

    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "DO $$ BEGIN "
                "IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'agent_memory_test') "
                "THEN CREATE ROLE agent_memory_test LOGIN PASSWORD 'app-test' "
                "NOSUPERUSER NOBYPASSRLS; "
                "END IF; END $$"
            )
        )
        connection.execute(text("GRANT agent_memory_app TO agent_memory_test"))
    engine.dispose()

    url = make_url(database_url).set(
        drivername="postgresql+psycopg_async",
        username="agent_memory_test",
        password="app-test",
    )
    return url.render_as_string(hide_password=False)
