from collections.abc import Iterator

import pytest
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
