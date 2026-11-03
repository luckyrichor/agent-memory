"""B3: nearest-first vector search (the shape an HNSW index can serve) against the exact scan.

The point of the shape change is not "an index exists" but that the candidate list survives the
tenant / status filtering. pgvector only guarantees that from 0.8 (iterative scans), so the
provider falls back to the exact scan where the setting is missing; both behaviours are pinned
here.

Deliberately absent: a test that the planner picks the HNSW index. Measured on 8k and 20k rows
(docs/optimization/measurements/b3-*) the planner never chose it while the candidate limit stayed
at 1000, because the exact scan is genuinely cheaper at that width. Pinning planner behaviour here
would only pin the row count of the fixture.
"""
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import event

from agent_memory.application.retrieval import RetrievalQuery
from agent_memory.domain.enums import MemoryStatus, MemoryType, ScopeKind
from agent_memory.domain.models import Memory, MemoryScope
from agent_memory.infrastructure import retrieval as retrieval_module
from agent_memory.infrastructure.db import (
    create_engine,
    create_session_factory,
    session_for_principal,
)
from agent_memory.infrastructure.orm import MemoryEmbeddingRow
from agent_memory.infrastructure.repositories import PostgresMemoryRepository
from agent_memory.infrastructure.retrieval import PostgresCandidateProvider

MODEL = "b3-test-model"
DIMENSIONS = 1024


def principal(tenant=None, user=None):
    from agent_memory.domain.principal import RequestPrincipal

    return RequestPrincipal(
        tenant or uuid4(),
        user or uuid4(),
        frozenset({"developer"}),
        frozenset({"memory:read", "memory:write"}),
        frozenset(),
    )


def unit_vector(axis: int, weight: float = 1.0) -> list[float]:
    vector = [0.01] * DIMENSIONS
    vector[axis % DIMENSIONS] = weight
    return vector


async def seed(sessions, who, count: int, model: str = MODEL) -> list:
    """Memories whose embedding for axis i points almost entirely along dimension i."""
    created = []
    async with session_for_principal(sessions, who) as session:
        now = datetime.now(UTC)
        for index in range(count):
            memory, version = Memory.create(
                tenant_id=who.tenant_id,
                memory_id=uuid4(),
                version_id=uuid4(),
                memory_type=MemoryType.SEMANTIC,
                scope=MemoryScope(ScopeKind.TENANT, None, None),
                owner_user_id=who.user_id,
                content=f"vector fixture {index}",
                now=now,
                status=MemoryStatus.ACTIVE,
            )
            await PostgresMemoryRepository(session).add(who.tenant_id, memory, version)
            session.add(
                MemoryEmbeddingRow(
                    tenant_id=who.tenant_id,
                    memory_version_id=version.version_id,
                    model=model,
                    embedding=unit_vector(index),
                    updated_at=now,
                )
            )
            created.append((memory.memory_id, version.version_id))
    return created


async def ids_from(app_url, who, query: RetrievalQuery, **provider_options) -> list:
    engine = create_engine(app_url)
    sessions = create_session_factory(engine)
    try:
        async with session_for_principal(sessions, who) as session:
            provider = PostgresCandidateProvider(session, **provider_options)
            return [candidate.memory_id for candidate in await provider.candidates(query, who)]
    finally:
        await engine.dispose()


async def test_nearest_first_returns_the_same_hits_as_the_exact_scan(app_database_url):
    who = principal()
    engine = create_engine(app_database_url)
    sessions = create_session_factory(engine)
    try:
        created = await seed(sessions, who, 30)
    finally:
        await engine.dispose()

    query = RetrievalQuery("", vector=tuple(unit_vector(7, 1.2)), model=MODEL, limit=10)
    exact = await ids_from(app_database_url, who, query, vector_search="exact")
    nearest = await ids_from(app_database_url, who, query, vector_search="nearest_first")
    assert exact[0] == created[7][0]
    assert nearest[:5] == exact[:5], "approximate search must not reshuffle the head of the list"
    assert set(nearest) <= {memory_id for memory_id, _ in created}


async def test_other_tenants_and_inactive_memories_never_leak_through_the_join(app_database_url):
    mine, theirs = principal(), principal()
    engine = create_engine(app_database_url)
    sessions = create_session_factory(engine)
    try:
        await seed(sessions, mine, 5)
        await seed(sessions, theirs, 5)
        async with session_for_principal(sessions, mine) as session:
            # Someone else's memory that is dead on arrival must not appear either.
            now = datetime.now(UTC)
            memory, version = Memory.create(
                tenant_id=mine.tenant_id,
                memory_id=uuid4(),
                version_id=uuid4(),
                memory_type=MemoryType.SEMANTIC,
                scope=MemoryScope(ScopeKind.TENANT, None, None),
                owner_user_id=mine.user_id,
                content="archived vector fixture",
                now=now,
                status=MemoryStatus.ARCHIVED,
            )
            await PostgresMemoryRepository(session).add(mine.tenant_id, memory, version)
            session.add(
                MemoryEmbeddingRow(
                    tenant_id=mine.tenant_id,
                    memory_version_id=version.version_id,
                    model=MODEL,
                    embedding=unit_vector(0, 5.0),
                    updated_at=now,
                )
            )
            archived_id = memory.memory_id
    finally:
        await engine.dispose()

    query = RetrievalQuery("", vector=tuple(unit_vector(0, 5.0)), model=MODEL, limit=50)
    found = await ids_from(app_database_url, mine, query, vector_search="nearest_first")
    assert archived_id not in found
    assert len(found) == 5


async def test_missing_iterative_scan_falls_back_to_the_exact_scan(app_database_url, monkeypatch):
    """pgvector < 0.8 truncates a filtered approximate scan, so the shape must not be used there."""
    who = principal()
    engine = create_engine(app_database_url)
    sessions = create_session_factory(engine)
    try:
        created = await seed(sessions, who, 12)
    finally:
        await engine.dispose()

    query = RetrievalQuery("", vector=tuple(unit_vector(3, 1.5)), model=MODEL, limit=10)
    monkeypatch.setattr(retrieval_module, "_ITERATIVE_SCAN", False)
    engine = create_engine(app_database_url)
    sessions = create_session_factory(engine)
    statements: list[str] = []

    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    try:
        async with session_for_principal(sessions, who) as session:
            provider = PostgresCandidateProvider(session, vector_search="nearest_first")
            found = [c.memory_id for c in await provider.candidates(query, who)]
    finally:
        await engine.dispose()

    assert found[0] == created[3][0]
    assert not any("hnsw.ef_search" in statement for statement in statements), (
        "the index-only settings must not be issued when the exact scan is used"
    )


async def test_nearest_first_is_the_shape_that_reaches_the_database(app_database_url, monkeypatch):
    """The branch must actually be taken: ranking inside memory_embeddings, joining afterwards."""
    who = principal()
    engine = create_engine(app_database_url)
    sessions = create_session_factory(engine)
    try:
        created = await seed(sessions, who, 12)
    finally:
        await engine.dispose()

    monkeypatch.setattr(retrieval_module, "_ITERATIVE_SCAN", True)
    engine = create_engine(app_database_url)
    sessions = create_session_factory(engine)
    statements: list[str] = []

    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    query = RetrievalQuery("", vector=tuple(unit_vector(4, 1.3)), model=MODEL, limit=10)
    try:
        async with session_for_principal(sessions, who) as session:
            provider = PostgresCandidateProvider(session, vector_search="nearest_first", ef_search=64)
            found = [c.memory_id for c in await provider.candidates(query, who)]
    finally:
        await engine.dispose()

    assert found[0] == created[4][0]
    assert any("MATERIALIZED" in statement for statement in statements), (
        "the nearest-first shape ranks in a materialised CTE"
    )
    assert any("hnsw.ef_search" in statement for statement in statements), (
        "the ef_search probe must be issued on the nearest-first path"
    )
