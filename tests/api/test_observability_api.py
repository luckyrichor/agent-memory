"""End-to-end observability: one request, one trace, no content anywhere."""

import json
import logging
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from agent_memory.api.app import create_app
from agent_memory.config import Settings
from agent_memory.observability import set_tracer_provider

TENANT_ID = UUID("31000000-0000-0000-0000-000000000001")
USER_ID = UUID("31000000-0000-0000-0000-000000000002")
SECRET_CONTENT = "the release pipeline fails unless --no-cache is passed"


@pytest.fixture
def exporter() -> Iterator[InMemorySpanExporter]:
    try:
        yield InMemorySpanExporter()
    finally:
        set_tracer_provider(None)


def capture(exporter: InMemorySpanExporter) -> None:
    """Start collecting spans.

    Called *after* ``create_app``: the app factory configures observability
    from its settings, which would otherwise reset the provider installed here.
    """
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    set_tracer_provider(provider)


def signing_material() -> tuple[str, str]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    public_pem = private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    return private_pem, public_pem


def bearer_token(private_key: str) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "iss": "memory-test",
            "aud": "memory-api",
            "sub": str(USER_ID),
            "tenant_id": str(TENANT_ID),
            "roles": ["developer"],
            "permissions": ["memory:read", "memory:write", "memory:delete"],
            "allowed_workspace_ids": ["project-a"],
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        private_key,
        algorithm="RS256",
    )


def build_app(app_database_url: str) -> tuple[object, str]:
    private_key, public_key = signing_material()
    app = create_app(
        Settings(
            database_url=app_database_url,
            jwt_public_key=public_key,
            jwt_issuer="memory-test",
            jwt_audience="memory-api",
        )
    )
    return app, bearer_token(private_key)


def remember_body() -> dict[str, object]:
    return {
        "content": SECRET_CONTENT,
        "memory_type": "semantic",
        "scope": {"kind": "user_global", "subject_user_id": str(USER_ID)},
    }


def names(spans: tuple[ReadableSpan, ...]) -> list[str]:
    return [span.name for span in spans]


@pytest.mark.asyncio
async def test_write_then_read_produces_one_trace_per_request(
    app_database_url: str,
    exporter: InMemorySpanExporter,
) -> None:
    app, token = build_app(app_database_url)
    capture(exporter)
    headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": "trace-write-1"}
    transport = ASGITransport(app=app)  # type: ignore[arg-type]

    async with AsyncClient(transport=transport, base_url="http://memory") as client:
        created = await client.post("/v1/memories", json=remember_body(), headers=headers)
        memory_id = created.json()["memory_id"]
        read = await client.get(f"/v1/memories/{memory_id}", headers=headers)
    await app.state.engine.dispose()  # type: ignore[attr-defined]

    assert created.status_code == 201
    assert read.status_code == 200

    spans = exporter.get_finished_spans()
    traces = {span.context.trace_id for span in spans if span.context is not None}
    assert len(traces) == 2, "each HTTP request gets its own trace"

    write_trace = [span for span in spans if span.name == "POST /v1/memories"]
    assert len(write_trace) == 1
    root = write_trace[0]
    assert root.parent is None
    assert root.attributes is not None
    assert root.attributes["http_status"] == 201
    assert root.attributes["route"] == "/v1/memories"


@pytest.mark.asyncio
async def test_the_write_trace_covers_handler_service_and_database(
    app_database_url: str,
    exporter: InMemorySpanExporter,
) -> None:
    app, token = build_app(app_database_url)
    capture(exporter)
    headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": "trace-write-2"}
    transport = ASGITransport(app=app)  # type: ignore[arg-type]

    async with AsyncClient(transport=transport, base_url="http://memory") as client:
        response = await client.post("/v1/memories", json=remember_body(), headers=headers)
    await app.state.engine.dispose()  # type: ignore[attr-defined]

    assert response.status_code == 201
    spans = exporter.get_finished_spans()
    assert {"POST /v1/memories", "db.session", "memory.remember"} <= set(names(spans))

    service = next(span for span in spans if span.name == "memory.remember")
    root = next(span for span in spans if span.name == "POST /v1/memories")
    assert service.context is not None and root.context is not None
    assert service.context.trace_id == root.context.trace_id
    assert service.attributes is not None
    assert service.attributes["reason_code"] == "MEMORY_CREATED"
    assert service.attributes["tenant_id"] == str(TENANT_ID)


@pytest.mark.asyncio
async def test_the_read_trace_reaches_the_service_span(
    app_database_url: str,
    exporter: InMemorySpanExporter,
) -> None:
    app, token = build_app(app_database_url)
    capture(exporter)
    headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": "trace-read-1"}
    transport = ASGITransport(app=app)  # type: ignore[arg-type]

    async with AsyncClient(transport=transport, base_url="http://memory") as client:
        created = await client.post("/v1/memories", json=remember_body(), headers=headers)
        memory_id = created.json()["memory_id"]
        exporter.clear()
        await client.get(f"/v1/memories/{memory_id}", headers=headers)
    await app.state.engine.dispose()  # type: ignore[attr-defined]

    spans = exporter.get_finished_spans()
    assert "memory.get_active" in names(spans)
    service = next(span for span in spans if span.name == "memory.get_active")
    assert service.attributes is not None
    assert service.attributes["reason_code"] == "MEMORY_RETURNED"


@pytest.mark.asyncio
async def test_no_span_or_log_line_carries_the_memory_content(
    app_database_url: str,
    exporter: InMemorySpanExporter,
    caplog: pytest.LogCaptureFixture,
) -> None:
    app, token = build_app(app_database_url)
    capture(exporter)
    headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": "trace-leak-1"}
    transport = ASGITransport(app=app)  # type: ignore[arg-type]

    with caplog.at_level(logging.INFO):
        async with AsyncClient(transport=transport, base_url="http://memory") as client:
            created = await client.post("/v1/memories", json=remember_body(), headers=headers)
            await client.get(f"/v1/memories/{created.json()['memory_id']}", headers=headers)
    await app.state.engine.dispose()  # type: ignore[attr-defined]

    exported = json.dumps([json.loads(span.to_json()) for span in exporter.get_finished_spans()])
    logged = " ".join(record.getMessage() for record in caplog.records)
    logged_fields = json.dumps(
        [getattr(record, "agent_memory_fields", {}) for record in caplog.records],
        default=str,
    )

    assert SECRET_CONTENT not in exported
    assert SECRET_CONTENT not in logged
    assert SECRET_CONTENT not in logged_fields
    assert "--no-cache" not in exported


@pytest.mark.asyncio
async def test_request_id_is_echoed_and_reused_in_error_bodies(
    app_database_url: str,
    exporter: InMemorySpanExporter,
) -> None:
    app, _ = build_app(app_database_url)
    capture(exporter)
    transport = ASGITransport(app=app)  # type: ignore[arg-type]

    async with AsyncClient(transport=transport, base_url="http://memory") as client:
        generated = await client.get(f"/v1/memories/{UUID(int=7)}")
        supplied = await client.get(
            f"/v1/memories/{UUID(int=7)}",
            headers={"X-Request-Id": "caller-supplied-id"},
        )
    await app.state.engine.dispose()  # type: ignore[attr-defined]

    assert generated.status_code == 401
    assert generated.headers["X-Request-Id"] == generated.json()["error"]["request_id"]
    assert supplied.headers["X-Request-Id"] == "caller-supplied-id"
    assert supplied.json()["error"]["request_id"] == "caller-supplied-id"
