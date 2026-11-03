"""D1 (SC4): search queries, event text and memory text must never reach logs or spans.

B0 (Agent report, not in the repo) found a query text leaking into logs 117 times, but the
raw logs were never committed, so the leak point is unknown. Reading the current code finds
no such path; this test is the guard: it drives every read/write path with unique marker
strings, captures *every* logger at DEBUG (not only ours) and every span, and asserts none
of the markers appears anywhere.
"""

import json
import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from agent_memory.api.app import create_app
from agent_memory.application.extraction import CodingFailureRuleExtractor
from agent_memory.application.extraction_worker import ExtractionWorker
from agent_memory.config import Settings
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
from agent_memory.observability import set_tracer_provider

TENANT_ID = UUID("39000000-0000-0000-0000-000000000001")
USER_ID = UUID("39000000-0000-0000-0000-000000000002")
NOW = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)

# Unique, unlikely-to-collide strings. Each stands for one kind of sensitive text.
QUERY_MARKER = "zxqv-query-marker-pelican-ledger"
BAD_QUERY_MARKER = "zxqv-bad-query-marker-walrus-anchor"
MEMORY_MARKER = "zxqv-memory-marker-heron-quartz"
EVENT_MARKER = "zxqv-event-marker-ibis-cobalt"
MARKERS = (QUERY_MARKER, BAD_QUERY_MARKER, MEMORY_MARKER, EVENT_MARKER)


def signing_keys() -> tuple[str, str]:
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return (
        private.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode(),
        private.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        ).decode(),
    )


def bearer(private: str) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "iss": "memory-test", "aud": "memory-api", "sub": str(USER_ID),
            "tenant_id": str(TENANT_ID), "roles": ["developer"],
            "permissions": ["memory:read", "memory:write", "memory:delete"],
            "allowed_workspace_ids": ["project-a"], "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        private, algorithm="RS256",
    )


def rendered(caplog: pytest.LogCaptureFixture) -> str:
    """Everything a log handler could emit: message, formatted args, exception text, fields."""
    parts: list[str] = []
    for record in caplog.records:
        parts.append(record.getMessage())
        parts.append(record.exc_text or "")
        parts.append(json.dumps(getattr(record, "agent_memory_fields", {}), default=str))
        parts.append(json.dumps(record.__dict__.get("args"), default=str))
    return "\n".join(parts)


async def run_extraction_worker(app_database_url: str) -> str:
    """Ingest one tool-result event and run the real extraction worker once."""
    ids = iter(UUID(f"39100000-0000-0000-0000-{n:012d}") for n in range(1, 1000))
    engine = create_engine(app_database_url)
    sessions = create_session_factory(engine)
    principal = RequestPrincipal(
        TENANT_ID, USER_ID, frozenset({"developer"}), frozenset({"memory:write"}),
        frozenset({"project-a"}),
    )
    draft = EventDraft(
        idempotency_key="d1-worker-event", session_id="d1-worker-session", sequence_number=1,
        event_type=EventType.TOOL_RESULT, agent_id="coding_agent", occurred_at=NOW,
        scope=MemoryScope(ScopeKind.WORKSPACE, "project-a", None),
        payload={"tool_name": "test", "exit_code": 1, "summary": EVENT_MARKER + " failed"},
    )
    async with session_for_principal(sessions, principal) as session:
        await PostgresEventIngestionRepository(
            session, new_id=lambda: next(ids), now=lambda: NOW
        ).ingest_batch(TENANT_ID, USER_ID, (draft,))
    async with session_for_principal(sessions, principal) as session:
        await PostgresOutboxRepository(
            session, new_id=lambda: next(ids), now=lambda: NOW
        ).dispatch_once(TENANT_ID, 10, "coding-failure-rule-v1")
    worker = ExtractionWorker(
        PostgresExtractionBackend(
            sessions, new_id=lambda: next(ids), now=lambda: NOW,
            activation="auto",
        ),
        CodingFailureRuleExtractor(),
        now=lambda: NOW,
        lease_duration=timedelta(seconds=30),
    )
    outcome = (await worker.run_once(TENANT_ID, "d1-worker")).outcome
    await engine.dispose()
    return outcome


@pytest.mark.asyncio
async def test_no_query_event_or_memory_text_reaches_any_log_or_span(
    app_database_url: str, caplog: pytest.LogCaptureFixture,
) -> None:
    private, public = signing_keys()
    app = create_app(
        Settings(
            database_url=app_database_url, jwt_public_key=public,
            jwt_issuer="memory-test", jwt_audience="memory-api",
        )
    )
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    set_tracer_provider(provider)  # after create_app: the factory resets observability
    headers = {"Authorization": f"Bearer {bearer(private)}"}
    scope = {"kind": "workspace", "workspace_id": "project-a"}
    statuses: dict[str, int] = {}
    try:
        # DEBUG on the root logger: also captures sqlalchemy, httpx, starlette, asyncio.
        with caplog.at_level(logging.DEBUG):
            async with AsyncClient(
                transport=ASGITransport(app=app),  # type: ignore[arg-type]
                base_url="http://memory",
            ) as client:
                statuses["remember"] = (await client.post(
                    "/v1/memories", headers={**headers, "Idempotency-Key": "d1-remember-1"},
                    json={"content": MEMORY_MARKER, "memory_type": "semantic", "scope": scope},
                )).status_code
                statuses["events"] = (await client.post(
                    "/v1/events:batch", headers=headers, json={"events": [{
                        "idempotency_key": "d1-api-event", "session_id": "d1-api-session",
                        "sequence_number": 1, "event_type": "conversation.message",
                        "agent_id": "chat_agent", "occurred_at": NOW.isoformat(),
                        "scope": scope,
                        "payload": {"role": "user", "summary": EVENT_MARKER},
                    }]},
                )).status_code
                statuses["search"] = (await client.post(
                    "/v1/memories/search", headers=headers,
                    json={"query": QUERY_MARKER, "workspace_id": "project-a"},
                )).status_code
                statuses["context"] = (await client.post(
                    "/v1/memories/context", headers=headers,
                    json={"query": QUERY_MARKER, "workspace_id": "project-a"},
                )).status_code
                # Rejected requests are the likeliest place for a validation error handler
                # to echo the offending input into a log line.
                statuses["bad_vector"] = (await client.post(
                    "/v1/memories/search", headers=headers,
                    json={"query": BAD_QUERY_MARKER, "vector": [0.5, 0.5]},
                )).status_code
                statuses["bad_limit"] = (await client.post(
                    "/v1/memories/search", headers=headers,
                    json={"query": BAD_QUERY_MARKER, "limit": 0},
                )).status_code
                statuses["unauthenticated"] = (await client.post(
                    "/v1/memories/search", json={"query": BAD_QUERY_MARKER},
                )).status_code
            worker_outcome = await run_extraction_worker(app_database_url)
    finally:
        await app.state.engine.dispose()  # type: ignore[attr-defined]
        set_tracer_provider(None)

    # The guard must not be vacuous: the paths really ran and really logged.
    assert statuses["remember"] == 201 and statuses["events"] in (200, 201, 202), statuses
    assert statuses["search"] == 200 and statuses["context"] == 200, statuses
    assert statuses["bad_vector"] == 422 and statuses["bad_limit"] == 422, statuses
    assert statuses["unauthenticated"] == 401, statuses
    assert worker_outcome == "succeeded"
    assert any(record.name.startswith("agent_memory") for record in caplog.records)
    spans = exporter.get_finished_spans()
    assert spans, "no spans were captured"

    logged = rendered(caplog)
    exported = json.dumps([json.loads(span.to_json()) for span in spans])
    for marker in MARKERS:
        assert marker not in logged, f"{marker} leaked into a log record"
        assert marker not in exported, f"{marker} leaked into a span"
