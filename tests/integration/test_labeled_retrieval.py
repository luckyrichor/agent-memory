import json
from datetime import UTC, datetime
from pathlib import Path

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


async def test_labeled_chinese_retrieval_recall_and_top_k(app_database_url):
    data = json.loads(Path("evals/datasets/retrieval-zh-v2.json").read_text())
    engine = create_engine(app_database_url)
    sessions = create_session_factory(engine)
    who = principal()
    identities = {}
    try:
        async with session_for_principal(sessions, who) as session:
            usecase = service(session, who, datetime.now(UTC))
            for item in data["memories"]:
                result = await usecase.remember(
                    RememberMemoryCommand(
                        item["content"],
                        MemoryType.SEMANTIC,
                        MemoryScope(ScopeKind.TENANT, None, None),
                        item["id"],
                    ),
                    who,
                )
                identities[result.memory_id] = item["id"]
        scores = []
        async with session_for_principal(sessions, who) as session:
            retriever = MemoryRetriever(PostgresCandidateProvider(session))
            for item in data["queries"]:
                page = await retriever.search(RetrievalQuery(item["query"], limit=3), who)
                found = [identities[h.memory_id] for h in page.items]
                relevant = set(item["relevant"])
                if relevant:
                    scores.append(
                        {
                            "query": item["query"],
                            "recall_at_3": len(relevant.intersection(found)) / len(relevant),
                            "hit_at_1": int(bool(found) and found[0] in relevant),
                        }
                    )
                    assert relevant.issubset(found)
                else:
                    assert found == []
        report = {
            "dataset": "retrieval-zh-v2",
            "queries": len(data["queries"]),
            "channel": "PostgreSQL Chinese bigram lexical, no vector provider",
            "recall_at_3": sum(s["recall_at_3"] for s in scores) / len(scores),
            "hit_at_1": sum(s["hit_at_1"] for s in scores) / len(scores),
            "limits": "small constructed keyword dataset; no general semantic-quality claim",
            "cases": scores,
        }
        Path("docs/measurements/followup-retrieval-zh.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n"
        )
    finally:
        await engine.dispose()
