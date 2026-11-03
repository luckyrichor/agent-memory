"""E3: the scorer reads real type/age/authority from the database, and the page order shows it.

Unit tests cover the arithmetic. What is only verifiable here is the join: that the metadata on a
hit is the row's metadata, scoped to the caller's tenant, and that changing a row's authority
actually moves it in the rendered context.
"""
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from test_review_hardening import principal, service

from agent_memory.application.commands import RememberMemoryCommand
from agent_memory.application.context_builder import MemoryContextBuilder
from agent_memory.application.retrieval import MemoryRetriever, RetrievalQuery
from agent_memory.domain.enums import AuthorityLevel, MemoryType, ScopeKind
from agent_memory.domain.models import MemoryScope
from agent_memory.infrastructure.db import (
    create_engine,
    create_session_factory,
    session_for_principal,
)
from agent_memory.infrastructure.retrieval import PostgresCandidateProvider


async def remember(sessions, who, key: str, content: str):
    async with session_for_principal(sessions, who) as session:
        return await service(session, who, datetime.now(UTC)).remember(
            RememberMemoryCommand(
                content, MemoryType.SEMANTIC, MemoryScope(ScopeKind.TENANT, None, None), key
            ),
            who,
        )


async def age_and_rank(sessions, who, version_id, *, days_old: float,
                       authority: AuthorityLevel, memory_type: MemoryType) -> None:
    """Rewrite the metadata the scorer reads, the way time and later verification would."""
    async with session_for_principal(sessions, who) as session:
        await session.execute(
            text(
                "UPDATE memory_versions SET created_at = :created, authority_level = :authority"
                " WHERE tenant_id = :tenant AND memory_version_id = :version"
            ),
            {
                "created": datetime.now(UTC) - timedelta(days=days_old),
                "authority": int(authority),
                "tenant": who.tenant_id,
                "version": version_id,
            },
        )
        await session.execute(
            text(
                "UPDATE memories SET memory_type = :kind"
                " WHERE tenant_id = :tenant AND memory_id = ("
                "  SELECT memory_id FROM memory_versions"
                "  WHERE tenant_id = :tenant AND memory_version_id = :version)"
            ),
            {"kind": memory_type.value, "tenant": who.tenant_id, "version": version_id},
        )


async def test_hits_carry_the_rows_type_age_and_authority(app_database_url):
    engine = create_engine(app_database_url)
    sessions = create_session_factory(engine)
    who = principal()
    try:
        created = await remember(sessions, who, "k1", "narwhal deploy checklist alpha")
        await age_and_rank(
            sessions, who, created.version_id, days_old=30,
            authority=AuthorityLevel.ENTERPRISE_POLICY, memory_type=MemoryType.PROCEDURAL,
        )
        async with session_for_principal(sessions, who) as session:
            page = await MemoryRetriever(PostgresCandidateProvider(session)).search(
                RetrievalQuery("narwhal deploy"), who
            )
    finally:
        await engine.dispose()

    (hit,) = page.items
    assert hit.memory_type is MemoryType.PROCEDURAL
    assert hit.authority_level == int(AuthorityLevel.ENTERPRISE_POLICY)
    assert hit.created_at is not None
    age = (datetime.now(UTC) - hit.created_at).total_seconds() / 86400
    assert 29 < age < 31


async def test_other_tenants_metadata_never_comes_back(app_database_url):
    engine = create_engine(app_database_url)
    sessions = create_session_factory(engine)
    mine, theirs = principal(), principal()
    try:
        own = await remember(sessions, mine, "k1", "pangolin release note mine")
        foreign = await remember(sessions, theirs, "k1", "pangolin release note theirs")
        async with session_for_principal(sessions, mine) as session:
            facts = await PostgresCandidateProvider(session).facts(
                [own.version_id, foreign.version_id], mine
            )
            assert set(facts) == {own.version_id}
            assert await PostgresCandidateProvider(session).facts([], mine) == {}
    finally:
        await engine.dispose()


async def test_context_prefers_the_authoritative_memory_when_relevance_ties(app_database_url):
    """Two equal-length memories that both match the query; only authority separates them."""
    engine = create_engine(app_database_url)
    sessions = create_session_factory(engine)
    who = principal()
    try:
        weak = await remember(sessions, who, "k1", "wombat rollout window weak")
        strong = await remember(sessions, who, "k2", "wombat rollout window strg")
        await age_and_rank(sessions, who, weak.version_id, days_old=1,
                           authority=AuthorityLevel.AGENT_INFERENCE,
                           memory_type=MemoryType.SEMANTIC)
        await age_and_rank(sessions, who, strong.version_id, days_old=1,
                           authority=AuthorityLevel.ENTERPRISE_POLICY,
                           memory_type=MemoryType.SEMANTIC)
        async with session_for_principal(sessions, who) as session:
            page = await MemoryRetriever(PostgresCandidateProvider(session)).search(
                RetrievalQuery("wombat rollout"), who
            )
    finally:
        await engine.dispose()

    assert len(page.items) == 2
    packet = MemoryContextBuilder().build(page.items, 100000, now=datetime.now(UTC))
    assert packet.selected_version_ids[0] == str(strong.version_id)
