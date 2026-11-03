"""B1: channels return ids only; bodies come from a second, tenant-scoped read of the page."""
from datetime import UTC, datetime

from test_review_hardening import principal, service

from agent_memory.application.commands import RememberMemoryCommand
from agent_memory.application.retrieval import MemoryRetriever, RetrievalQuery
from agent_memory.domain.enums import MemoryType, ScopeKind
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


async def test_contents_returns_bodies_for_own_tenant_and_nothing_for_foreign_ids(
    app_database_url,
):
    engine = create_engine(app_database_url)
    sessions = create_session_factory(engine)
    mine, theirs = principal(), principal()
    try:
        own = await remember(sessions, mine, "own", "zebrafish pipeline note alpha")
        foreign = await remember(sessions, theirs, "foreign", "zebrafish private note beta")
        async with session_for_principal(sessions, mine) as session:
            provider = PostgresCandidateProvider(session)
            found = await provider.contents(
                [own.version_id, foreign.version_id], mine
            )
            assert found == {own.version_id: "zebrafish pipeline note alpha"}
            assert await provider.contents([], mine) == {}
    finally:
        await engine.dispose()


async def test_page_bodies_match_hits_and_candidates_carry_no_body(app_database_url):
    engine = create_engine(app_database_url)
    sessions = create_session_factory(engine)
    who = principal()
    try:
        for index in range(6):
            await remember(sessions, who, f"k{index}", f"quokka telemetry entry number {index}")
        async with session_for_principal(sessions, who) as session:
            provider = PostgresCandidateProvider(session)
            candidates = await provider.candidates(RetrievalQuery("quokka telemetry"), who)
            assert len(candidates) == 6
            assert not hasattr(candidates[0], "content")  # id + score only
            page = await MemoryRetriever(provider).search(
                RetrievalQuery("quokka telemetry", limit=4), who
            )
            assert len(page.items) == 4 and page.next_offset == 4
            assert all("quokka telemetry entry number" in hit.content for hit in page.items)
    finally:
        await engine.dispose()


async def test_candidate_limit_caps_every_channel(app_database_url):
    engine = create_engine(app_database_url)
    sessions = create_session_factory(engine)
    who = principal()
    try:
        for index in range(5):
            await remember(sessions, who, f"c{index}", f"axolotl regeneration log {index}")
        async with session_for_principal(sessions, who) as session:
            capped = PostgresCandidateProvider(session, candidate_limit=2)
            candidates = await capped.candidates(
                RetrievalQuery("axolotl regeneration", workspace_id=None), who
            )
            assert len(candidates) == 2
            page = await MemoryRetriever(capped).search(
                RetrievalQuery("axolotl regeneration", limit=10), who
            )
            assert page.channel_counts["lexical"] == 2 and len(page.items) == 2
    finally:
        await engine.dispose()


async def test_stored_lexical_vectors_equal_the_expressions_they_replace(app_database_url):
    """B2: lexical_en / lexical_zh must be exactly the old per-row to_tsvector expressions."""
    from sqlalchemy import select, text

    from agent_memory.infrastructure.orm import MemoryVersionRow

    engine = create_engine(app_database_url)
    sessions = create_session_factory(engine)
    who = principal()
    try:
        await remember(sessions, who, "mixed", "部署失败 Java17 stemming runs, deployments failed")
        async with session_for_principal(sessions, who) as session:
            same = (
                await session.execute(
                    text(
                        "SELECT lexical_en = to_tsvector('english', content),"
                        " lexical_zh = to_tsvector('simple', memory_lexical_tokens(content)),"
                        " lexical_en IS NOT NULL AND lexical_zh IS NOT NULL"
                        " FROM memory_versions"
                    )
                )
            ).one()
            assert tuple(same) == (True, True, True)
            # whole-entity loads must not fetch the two vectors (deferred columns)
            statement = str(select(MemoryVersionRow).compile())
            assert "lexical_en" not in statement and "lexical_zh" not in statement
    finally:
        await engine.dispose()


async def test_both_languages_still_retrieve_through_the_stored_vectors(app_database_url):
    engine = create_engine(app_database_url)
    sessions = create_session_factory(engine)
    who = principal()
    try:
        english = await remember(sessions, who, "en", "The nightly pipelines were rebuilt")
        chinese = await remember(sessions, who, "zh", "夜间流水线已经重新构建完成")
        async with session_for_principal(sessions, who) as session:
            retriever = MemoryRetriever(PostgresCandidateProvider(session))
            found_en = await retriever.search(RetrievalQuery("rebuilding pipeline"), who)
            found_zh = await retriever.search(RetrievalQuery("流水线构建"), who)
        assert [h.memory_id for h in found_en.items] == [english.memory_id]  # stemmed match
        assert chinese.memory_id in [h.memory_id for h in found_zh.items]
    finally:
        await engine.dispose()
