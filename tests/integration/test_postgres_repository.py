from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, inspect, text

from agent_memory.domain.enums import MemoryType, ScopeKind
from agent_memory.domain.models import Memory, MemoryScope
from agent_memory.domain.principal import RequestPrincipal
from agent_memory.infrastructure.db import (
    create_engine as create_async_engine,
)
from agent_memory.infrastructure.db import create_session_factory, session_for_principal
from agent_memory.infrastructure.repositories import PostgresMemoryRepository

TENANT_A = UUID("00000000-0000-0000-0000-00000000000a")
USER_A = UUID("00000000-0000-0000-0000-00000000000b")
MEMORY_ID = UUID("00000000-0000-0000-0000-00000000000c")
VERSION_1_ID = UUID("00000000-0000-0000-0000-00000000000d")
VERSION_2_ID = UUID("00000000-0000-0000-0000-00000000000e")
NOW = datetime(2026, 8, 30, 14, 0, tzinfo=UTC)


def principal_a() -> RequestPrincipal:
    return RequestPrincipal(
        tenant_id=TENANT_A,
        user_id=USER_A,
        roles=frozenset({"developer"}),
        permissions=frozenset({"memory:read", "memory:write"}),
        allowed_workspace_ids=frozenset({"project-a"}),
    )

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

    memory_foreign_keys = inspector.get_foreign_keys("memories")
    assert any(
        foreign_key["referred_table"] == "memory_versions"
        and foreign_key["constrained_columns"]
        == ["tenant_id", "memory_id", "current_version_id"]
        and foreign_key["referred_columns"]
        == ["tenant_id", "memory_id", "memory_version_id"]
        for foreign_key in memory_foreign_keys
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


@pytest.mark.asyncio
async def test_postgres_repository_round_trip_and_optimistic_update(
    app_database_url: str,
) -> None:
    engine = create_async_engine(app_database_url)
    sessions = create_session_factory(engine)
    memory, version_1 = Memory.create(
        tenant_id=TENANT_A,
        memory_id=MEMORY_ID,
        version_id=VERSION_1_ID,
        memory_type=MemoryType.SEMANTIC,
        scope=MemoryScope(ScopeKind.WORKSPACE, "project-a", None),
        owner_user_id=USER_A,
        content="项目 A 使用 Java 17",
        now=NOW,
    )

    async with session_for_principal(sessions, principal_a()) as session:
        repository = PostgresMemoryRepository(session)
        await repository.add(TENANT_A, memory, version_1)

    updated, version_2 = memory.add_version(
        version_id=VERSION_2_ID,
        content="项目 A 已升级为 Java 21",
        expected_revision=1,
        now=NOW,
    )
    async with session_for_principal(sessions, principal_a()) as session:
        repository = PostgresMemoryRepository(session)
        await repository.append_version(TENANT_A, updated, version_2, expected_revision=1)

    async with session_for_principal(sessions, principal_a()) as session:
        record = await PostgresMemoryRepository(session).get(TENANT_A, MEMORY_ID)

    assert record is not None
    assert record.memory.revision == 2
    assert [version.content for version in record.versions] == [
        "项目 A 使用 Java 17",
        "项目 A 已升级为 Java 21",
    ]
    await engine.dispose()
