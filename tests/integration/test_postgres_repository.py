from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, inspect, text


@pytest.fixture(scope="module")
def migrated_engine(database_url: str) -> Iterator[Engine]:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")
    engine = create_engine(database_url)
    try:
        yield engine
    finally:
        engine.dispose()


def test_migration_creates_foundation_schema(migrated_engine: Engine) -> None:
    inspector = inspect(migrated_engine)
    expected_tables = {
        "memories",
        "memory_versions",
        "idempotency_records",
        "audit_logs",
    }

    assert expected_tables <= set(inspector.get_table_names())
    for table in expected_tables:
        assert "tenant_id" in {column["name"] for column in inspector.get_columns(table)}

    version_foreign_keys = inspector.get_foreign_keys("memory_versions")
    assert any(
        foreign_key["referred_table"] == "memories"
        and foreign_key["constrained_columns"] == ["tenant_id", "memory_id"]
        for foreign_key in version_foreign_keys
    )

    version_uniques = inspector.get_unique_constraints("memory_versions")
    assert any(
        constraint["column_names"] == ["tenant_id", "memory_id", "version_number"]
        for constraint in version_uniques
    )


def test_migration_enables_pgvector(migrated_engine: Engine) -> None:
    with migrated_engine.connect() as connection:
        installed = connection.execute(
            text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')")
        ).scalar_one()

    assert installed is True
