import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx
from sqlalchemy import func, select

from agent_memory.application.extraction_worker import ExtractionWorker
from agent_memory.domain.enums import ScopeKind
from agent_memory.domain.events import EventDraft, EventType
from agent_memory.domain.models import MemoryScope
from agent_memory.domain.principal import RequestPrincipal
from agent_memory.infrastructure.db import (
    create_engine,
    create_session_factory,
    session_for_principal,
)
from agent_memory.infrastructure.event_repositories import (
    PostgresEventIngestionRepository,
    PostgresExtractionBackend,
    PostgresOutboxRepository,
)
from agent_memory.infrastructure.llm_extractor import LLMExtractor
from agent_memory.infrastructure.orm import MemoryRow, MemoryVersionRow


async def test_llm_event_worker_candidate_pipeline(app_database_url: str) -> None:
    tenant, user = uuid4(), uuid4()
    principal = RequestPrincipal(tenant, user, frozenset(), frozenset({"memory:write"}),
                                 frozenset({"private"}))
    engine = create_engine(app_database_url)
    sessions = create_session_factory(engine)
    now = lambda: datetime.now(UTC)
    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(
            {"memories": [{"content": "Check deployment configuration before restarting"}]})}}]})
    model = LLMExtractor("https://provider.test/chat", "fixed-response-v1", "test",
                         transport=httpx.MockTransport(respond))
    real = os.environ.get("MEMORY_EVAL_REAL_EXTRACTION") == "1"
    if real:
        values = dict(line.split("=", 1) for line in Path(".local/ark.env").read_text()
                      .splitlines() if "=" in line and not line.startswith("#"))
        model = LLMExtractor(values["MEMORY_EXTRACTION_ENDPOINT"],
                             values["MEMORY_EXTRACTION_MODEL"], values["ARK_API_KEY"])
    try:
        events = tuple(EventDraft(str(index), "pipeline", index, kind, "ops", now(),
            MemoryScope(ScopeKind.WORKSPACE, "private", None), {"summary": summary})
            for index, (kind, summary) in enumerate([
                (EventType.TASK_COMPLETED, "Deployment failed on missing configuration; validate config before restart."),
                (EventType.USER_CONFIRMED, "Always check target architecture before rebuilding dependencies."),
                (EventType.TASK_COMPLETED, "Contact alice@example.test; password=synthetic-only"),
            ], 1))
        async with session_for_principal(sessions, principal) as session:
            await PostgresEventIngestionRepository(session, new_id=uuid4, now=now).ingest_batch(
                tenant, user, events)
        async with session_for_principal(sessions, principal) as session:
            assert await PostgresOutboxRepository(session, new_id=uuid4, now=now).dispatch_once(
                tenant, 10, model.version) == 3
        worker = ExtractionWorker(PostgresExtractionBackend(sessions, new_id=uuid4, now=now),
                                  model, now=now, lease_duration=timedelta(seconds=30))
        reasons = []
        failures = []
        for _ in events:
            assert (await worker.run_once(tenant, "llm-test")).outcome == "succeeded"
            reasons.append(model.last_reason)
            failures.append(model.last_failure)
        assert reasons.count("LLM_EXTRACTED") == 2, (reasons, failures)
        assert reasons.count("INPUT_POLICY_REJECTED") == 1
        async with session_for_principal(sessions, principal) as session:
            memories = list((await session.scalars(select(MemoryRow))).all())
            assert len(memories) >= 2
            assert all(m.status == "candidate" and m.workspace_id == "private" for m in memories)
            versions = list((await session.scalars(select(MemoryVersionRow))).all())
            assert all(v.authority_level == 0 and v.verification_status == "unverified" for v in versions)
            assert not any("alice@example" in v.content or "password" in v.content for v in versions)
        other = RequestPrincipal(uuid4(), user, frozenset(), frozenset(), frozenset())
        async with session_for_principal(sessions, other) as session:
            assert await session.scalar(select(func.count()).select_from(MemoryRow)) == 0
        if real:
            Path("docs/measurements/w8-real-llm-pipeline.json").write_text(json.dumps({
                "model": model.model, "event_jobs_succeeded": 3, "llm_events": 2,
                "sensitive_events_rejected": 1, "candidate_count": len(memories),
                "scope_preserved": True, "authority_escalations": 0, "tenant_leaks": 0,
                "limitations": "2 synthetic non-build events; no general extraction-quality claim",
            }, indent=2)+"\n")
    finally:
        await engine.dispose()
