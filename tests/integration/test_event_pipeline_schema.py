from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, inspect, text

PIPELINE_TABLES = {"events", "outbox_messages", "jobs", "evidence"}


@pytest.fixture(scope="module")
def pipeline_engine(database_url: str) -> Iterator[Engine]:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")
    engine = create_engine(database_url)
    try:
        yield engine
    finally:
        engine.dispose()


def test_event_pipeline_schema_has_tenant_keys_constraints_and_rls(
    pipeline_engine: Engine,
) -> None:
    inspector = inspect(pipeline_engine)

    assert PIPELINE_TABLES <= set(inspector.get_table_names())
    for table in PIPELINE_TABLES:
        assert "tenant_id" in {column["name"] for column in inspector.get_columns(table)}

    event_uniques = {
        tuple(constraint["column_names"])
        for constraint in inspector.get_unique_constraints("events")
    }
    assert ("tenant_id", "idempotency_key") in event_uniques
    assert ("tenant_id", "session_id", "sequence_number") in event_uniques

    job_uniques = {
        tuple(constraint["column_names"])
        for constraint in inspector.get_unique_constraints("jobs")
    }
    assert ("tenant_id", "job_type", "idempotency_key") in job_uniques

    evidence_foreign_keys = inspector.get_foreign_keys("evidence")
    assert any(
        key["referred_table"] == "events"
        and key["constrained_columns"] == ["tenant_id", "event_id"]
        for key in evidence_foreign_keys
    )
    assert any(
        key["referred_table"] == "memory_versions"
        and key["constrained_columns"] == ["tenant_id", "memory_version_id"]
        for key in evidence_foreign_keys
    )

    with pipeline_engine.connect() as connection:
        rls_rows = connection.execute(
            text(
                "SELECT relname, relrowsecurity, relforcerowsecurity "
                "FROM pg_class WHERE relname = ANY(:tables)"
            ),
            {"tables": sorted(PIPELINE_TABLES)},
        ).all()

    assert {row.relname for row in rls_rows} == PIPELINE_TABLES
    assert all(row.relrowsecurity and row.relforcerowsecurity for row in rls_rows)


def test_event_pipeline_migration_round_trip(database_url: str) -> None:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)

    command.downgrade(config, "0002_current_version_integrity")
    engine = create_engine(database_url)
    try:
        assert PIPELINE_TABLES.isdisjoint(inspect(engine).get_table_names())
    finally:
        engine.dispose()

    command.upgrade(config, "head")
    engine = create_engine(database_url)
    try:
        assert PIPELINE_TABLES <= set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
