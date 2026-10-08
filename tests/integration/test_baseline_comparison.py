"""Synthetic build-fault replay against real PostgreSQL, with optional real vectors.

This is a lifecycle regression benchmark, not a general LLM quality claim.
"""

import asyncio
import json
import os
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx
from sqlalchemy import select

from agent_memory.application.commands import (
    CorrectMemoryCommand,
    DisableMemoryCommand,
    RememberMemoryCommand,
)
from agent_memory.application.explicit_memory import ExplicitMemoryService
from agent_memory.application.retrieval import MemoryRetriever, RetrievalQuery
from agent_memory.domain.enums import MemoryStatus, MemoryType, ScopeKind
from agent_memory.domain.events import Event, EventDraft, EventType
from agent_memory.domain.models import MemoryScope
from agent_memory.domain.principal import RequestPrincipal
from agent_memory.infrastructure.db import (
    create_engine,
    create_session_factory,
    session_for_principal,
)
from agent_memory.infrastructure.embedding import HTTPEmbeddingProvider
from agent_memory.infrastructure.llm_extractor import LLMExtractor
from agent_memory.infrastructure.orm import MemoryEmbeddingRow, MemoryVersionRow
from agent_memory.infrastructure.repositories import (
    PostgresAuditSink,
    PostgresIdempotencyRepository,
    PostgresMemoryRepository,
)
from agent_memory.infrastructure.retrieval import PostgresCandidateProvider


async def test_postgres_fault_replay_baseline_comparison(app_database_url: str) -> None:
    at = datetime.now(UTC)
    engine = create_engine(app_database_url)
    sessions = create_session_factory(engine)
    scope = MemoryScope(ScopeKind.WORKSPACE, "build-replay", None)
    report: dict[str, object] = {
        "benchmark": "synthetic-build-lifecycle-v1",
        "environment": "PostgreSQL16+pgvector, native C++ compile and run",
        "cases": [],
        "embedding": "fixed-vector-fixture",
    }
    rows = []
    try:
        async with httpx.AsyncClient(trust_env=False, timeout=20) as client:
            provider = None
            if os.environ.get("MEMORY_EVAL_REAL_EMBEDDING") == "1":
                values = dict(
                    line.split("=", 1)
                    for line in Path(".local/ark.env").read_text().splitlines()
                    if "=" in line and not line.startswith("#")
                )
                provider = HTTPEmbeddingProvider(
                    client,
                    endpoint=values["ARK_EMBEDDING_ENDPOINT"],
                    model=values["ARK_EMBEDDING_MODEL"],
                    token=values["ARK_API_KEY"],
                    protocol="ark",
                )
                report["embedding"] = provider.model
            for case in ("active", "ordinary", "corrected", "deleted"):
                principal = RequestPrincipal(
                    uuid4(),
                    uuid4(),
                    frozenset(),
                    frozenset({"memory:read", "memory:write", "memory:delete"}),
                    frozenset({"build-replay"}),
                )

                def service(session):
                    return ExplicitMemoryService(
                        memory_repository=PostgresMemoryRepository(session),
                        idempotency_repository=PostgresIdempotencyRepository(session, lambda: at),
                        audit_sink=PostgresAuditSink(session, new_id=uuid4, now=lambda: at),
                        new_id=uuid4,
                        now=lambda: at,
                    )

                old_text = "repair dependency by selecting architecture x86"
                good_text = (
                    old_text
                    if case in ("active", "ordinary")
                    else "repair dependency by selecting architecture arm64"
                )

                async def extracted(content: str, principal: RequestPrincipal = principal) -> str:
                    # Fixed M7 response makes evaluation independent of online LLM
                    # drift. Explicit remember below represents user confirmation.
                    model = LLMExtractor(
                        "https://fixture.test/chat",
                        "fixed-lifecycle-v1",
                        "test",
                        transport=httpx.MockTransport(
                            lambda _: httpx.Response(
                                200,
                                json={
                                    "choices": [
                                        {
                                            "message": {
                                                "content": json.dumps(
                                                    {"memories": [{"content": content}]}
                                                )
                                            }
                                        }
                                    ]
                                },
                            )
                        ),
                    )
                    candidates = await model.extract(
                        Event(
                            principal.tenant_id,
                            uuid4(),
                            EventDraft(
                                "fixture",
                                "fixture",
                                1,
                                EventType.TASK_COMPLETED,
                                "fixture",
                                at,
                                scope,
                                {"summary": content},
                            ),
                            principal.user_id,
                            at,
                        )
                    )
                    assert model.last_reason == "LLM_EXTRACTED"
                    return candidates[0].content

                old_text, good_text = await extracted(old_text), await extracted(good_text)
                async with session_for_principal(sessions, principal) as session:
                    original = await service(session).remember(
                        RememberMemoryCommand(old_text, MemoryType.PROCEDURAL, scope, "initial"),
                        principal,
                    )
                    current = original
                    if case == "corrected":
                        current = await service(session).correct(
                            CorrectMemoryCommand(
                                original.memory_id, original.revision, good_text, "correct"
                            ),
                            principal,
                        )
                    if case == "deleted":
                        await service(session).disable(
                            DisableMemoryCommand(
                                original.memory_id,
                                original.revision,
                                MemoryStatus.DELETED,
                                "delete",
                            ),
                            principal,
                        )
                        current = await service(session).remember(
                            RememberMemoryCommand(
                                good_text, MemoryType.PROCEDURAL, scope, "replacement"
                            ),
                            principal,
                        )
                old_vector = await provider.embed(old_text) if provider else [1.0] + [0.0] * 1023
                good_vector = (
                    await provider.embed(good_text) if provider else [0.9, 0.1] + [0.0] * 1022
                )
                model = provider.model if provider else "fixture-lifecycle-v1"
                async with session_for_principal(sessions, principal) as session:
                    session.add(
                        MemoryEmbeddingRow(
                            tenant_id=principal.tenant_id,
                            memory_version_id=original.version_id,
                            model=model,
                            embedding=old_vector,
                            updated_at=at,
                        )
                    )
                    if current.version_id != original.version_id:
                        session.add(
                            MemoryEmbeddingRow(
                                tenant_id=principal.tenant_id,
                                memory_version_id=current.version_id,
                                model=model,
                                embedding=good_vector,
                                updated_at=at,
                            )
                        )
                async with session_for_principal(sessions, principal) as session:
                    query = RetrievalQuery(
                        "repair dependency",
                        tuple(old_vector),
                        model,
                        workspace_id="build-replay",
                        limit=1,
                    )
                    page = await MemoryRetriever(PostgresCandidateProvider(session)).search(
                        query, principal
                    )
                    # Same app identity/RLS, corpus, dimensions and query; baseline
                    # omits only lifecycle/current-version filtering and lexical fusion.
                    distance = MemoryEmbeddingRow.embedding.cosine_distance(old_vector)
                    naive = await session.scalar(
                        select(MemoryVersionRow.content)
                        .join(
                            MemoryEmbeddingRow,
                            (MemoryEmbeddingRow.tenant_id == MemoryVersionRow.tenant_id)
                            & (
                                MemoryEmbeddingRow.memory_version_id
                                == MemoryVersionRow.memory_version_id
                            ),
                        )
                        .where(MemoryVersionRow.tenant_id == principal.tenant_id)
                        .order_by(
                            distance, MemoryVersionRow.created_at, MemoryVersionRow.version_number
                        )
                        .limit(1)
                    )
                    filtered = await MemoryRetriever(PostgresCandidateProvider(session)).search(
                        RetrievalQuery("", tuple(old_vector), model, limit=1), principal
                    )
                    selected = {
                        "filtered_vector": filtered.items[0].content if filtered.items else None,
                        "no_memory": None,
                        "naive_vector": naive,
                        "system": page.items[0].content if page.items else None,
                    }
                    outcomes = {}
                    with tempfile.TemporaryDirectory(prefix="memory-build-eval-") as temporary:
                        root = Path(temporary)
                        for directory, api in (("x86", "v1"), ("arm64", "v2")):
                            (root / directory).mkdir()
                            (root / directory / "dependency.hpp").write_text(
                                f"inline int dependency_{api}() {{ return 42; }}\n"
                            )
                        target_api = "v1" if case in ("active", "ordinary") else "v2"
                        source = root / "main.cpp"
                        source.write_text(
                            '#include "dependency.hpp"\n'
                            f"int main() {{ return dependency_{target_api}() != 42; }}\n"
                        )
                        for name, lesson in selected.items():
                            # Whitelist maps lessons to fixture include paths. Labels
                            # are synthetic, not actual cross compilation. Retrieved
                            # content is never executable code or shell arguments.
                            action = (
                                "x86"
                                if lesson == old_text
                                else "arm64"
                                if lesson == good_text
                                else "none"
                            )
                            executable = root / "app"
                            compiled = await asyncio.to_thread(
                                subprocess.run,
                                [
                                    "g++",
                                    "-std=c++20",
                                    "-I",
                                    str(root / action),
                                    str(source),
                                    "-o",
                                    str(executable),
                                ],
                                capture_output=True,
                                check=False,
                                timeout=10,
                            )
                            success = compiled.returncode == 0
                            if success:
                                executed = await asyncio.to_thread(
                                    subprocess.run,
                                    [str(executable)],
                                    capture_output=True,
                                    check=False,
                                    timeout=5,
                                )
                                success = executed.returncode == 0
                            outcomes[name] = success
                    rows.append({"case": case, "success": outcomes})
                    assert outcomes["system"]
            report["cases"] = rows
            report["extraction"] = (
                "M7 adapter with fixed JSON responses, then explicit user confirmation"
            )
            report["successful_replays"] = {
                name: sum(row["success"][name] for row in rows)
                for name in ("no_memory", "naive_vector", "filtered_vector", "system")
            }
            report["limits"] = (
                "4 constructed cases incl ordinary; filtered-vector ablation; not general model-quality evidence"
            )
            path = Path(
                "docs/measurements/hardening-baselines-real.json"
                if provider
                else "docs/measurements/hardening-baselines-fixture.json"
            )
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(report, indent=2) + "\n")
    finally:
        await engine.dispose()
