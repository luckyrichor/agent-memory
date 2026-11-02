"""A1: extracted candidates must have a path to retrievability (B0 defect).

Before this task, extracted memories stayed ``candidate`` forever and search saw nothing.
"""
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient

from agent_memory.api.app import create_app
from agent_memory.application.extraction import CodingFailureRuleExtractor
from agent_memory.application.extraction_worker import ExtractionWorker
from agent_memory.config import Settings
from agent_memory.domain.activation import ActivationMode
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

TENANT_ID = UUID("36000000-0000-0000-0000-000000000001")
USER_ID = UUID("36000000-0000-0000-0000-000000000002")
NOW = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
SUMMARIES = {  # disjoint vocabulary per test: tests share one tenant and one database
    "11": "dependency conflict on arm64 resolved by pinning protobuf",
    "12": "kubernetes ingress timeout fixed by raising proxy buffer",
    "13": "grpc deadline exceeded traced to missing retry budget",
}
QUERIES = {
    "11": "protobuf arm64 dependency conflict",
    "12": "kubernetes ingress proxy buffer timeout",
    "13": "grpc deadline retry budget",
}


def new_ids(prefix: int) -> Iterator[UUID]:
    number = 1
    while True:
        yield UUID(f"{prefix:08d}-0000-0000-0000-{number:012d}")
        number += 1


def worker_principal() -> RequestPrincipal:
    return RequestPrincipal(
        TENANT_ID, USER_ID, frozenset({"developer"}), frozenset({"memory:write"}),
        frozenset({"project-a"}),
    )


async def run_pipeline(app_database_url: str, mode: ActivationMode, key: str) -> None:
    engine = create_engine(app_database_url)
    sessions = create_session_factory(engine)
    ids = new_ids(int(key))
    draft = EventDraft(
        idempotency_key=f"a1-{key}", session_id=f"a1-session-{key}", sequence_number=1,
        event_type=EventType.TOOL_RESULT, agent_id="coding_agent", occurred_at=NOW,
        scope=MemoryScope(ScopeKind.WORKSPACE, "project-a", None),
        payload={"tool_name": "test", "exit_code": 1, "summary": SUMMARIES[key]},
    )
    async with session_for_principal(sessions, worker_principal()) as session:
        await PostgresEventIngestionRepository(
            session, new_id=lambda: next(ids), now=lambda: NOW
        ).ingest_batch(TENANT_ID, USER_ID, (draft,))
    async with session_for_principal(sessions, worker_principal()) as session:
        await PostgresOutboxRepository(
            session, new_id=lambda: next(ids), now=lambda: NOW
        ).dispatch_once(TENANT_ID, 10, "coding-failure-rule-v1")
    worker = ExtractionWorker(
        PostgresExtractionBackend(
            sessions, new_id=lambda: next(ids), now=lambda: NOW, activation=mode
        ),
        CodingFailureRuleExtractor(),
        now=lambda: NOW,
        lease_duration=timedelta(seconds=30),
    )
    assert (await worker.run_once(TENANT_ID, "a1-worker")).outcome == "succeeded"
    await engine.dispose()


def keys() -> tuple[str, str]:
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


def token(private: str, permissions: list[str]) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "iss": "memory-test", "aud": "memory-api", "sub": str(USER_ID),
            "tenant_id": str(TENANT_ID), "roles": ["developer"], "permissions": permissions,
            "allowed_workspace_ids": ["project-a"], "iat": now, "exp": now + timedelta(minutes=5),
        },
        private, algorithm="RS256",
    )


@pytest.mark.asyncio
async def test_auto_activation_makes_extracted_memory_searchable(app_database_url: str) -> None:
    await run_pipeline(app_database_url, "auto", "11")
    private, public = keys()
    app = create_app(Settings(
        database_url=app_database_url, jwt_public_key=public,
        jwt_issuer="memory-test", jwt_audience="memory-api",
    ))
    headers = {"Authorization": "Bearer " + token(private, ["memory:read"])}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        found = (await client.post(
            "/v1/memories/search", headers=headers,
            json={"query": QUERIES["11"], "limit": 5},
        )).json()
    await app.state.engine.dispose()
    assert any("protobuf" in item["content"] for item in found["items"])


@pytest.mark.asyncio
async def test_manual_candidate_is_invisible_until_confirmed(app_database_url: str) -> None:
    await run_pipeline(app_database_url, "manual", "12")
    private, public = keys()
    app = create_app(Settings(
        database_url=app_database_url, jwt_public_key=public,
        jwt_issuer="memory-test", jwt_audience="memory-api",
    ))
    reader = {"Authorization": "Bearer " + token(private, ["memory:read"])}
    reviewer = {"Authorization": "Bearer " + token(private, ["memory:read", "memory:review"])}
    query = {"query": QUERIES["12"], "limit": 5}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        before = (await client.post("/v1/memories/search", headers=reader, json=query)).json()
        assert before["items"] == []

        # A reader without memory:review can neither see the queue nor decide.
        assert (await client.get(
            "/v1/memories/review-queue?status=candidate", headers=reader)).status_code == 403

        queue = (await client.get(
            "/v1/memories/review-queue?status=candidate", headers=reviewer)).json()
        mine = [i for i in queue["items"] if "kubernetes" in i["content"]]
        assert len(mine) == 1 and mine[0]["status"] == "candidate"
        memory_id, revision = mine[0]["memory_id"], mine[0]["revision"]

        stale = await client.post(
            f"/v1/memories/{memory_id}/confirm", headers=reviewer,
            json={"expected_revision": revision + 5},
        )
        assert stale.status_code == 409  # optimistic concurrency still applies

        assert (await client.post(
            f"/v1/memories/{memory_id}/confirm", headers=reader,
            json={"expected_revision": revision},
        )).status_code == 403

        confirmed = await client.post(
            f"/v1/memories/{memory_id}/confirm", headers=reviewer,
            json={"expected_revision": revision},
        )
        assert confirmed.status_code == 200 and confirmed.json()["status"] == "active"
        after = (await client.post("/v1/memories/search", headers=reader, json=query)).json()
        assert [i["memory_id"] for i in after["items"]] == [memory_id]

        # Deciding twice is rejected: it is no longer unreviewed.
        again = await client.post(
            f"/v1/memories/{memory_id}/reject", headers=reviewer,
            json={"expected_revision": revision + 1},
        )
        assert again.status_code == 409
    await app.state.engine.dispose()


@pytest.mark.asyncio
async def test_rejected_candidate_never_becomes_searchable(app_database_url: str) -> None:
    await run_pipeline(app_database_url, "manual", "13")
    private, public = keys()
    app = create_app(Settings(
        database_url=app_database_url, jwt_public_key=public,
        jwt_issuer="memory-test", jwt_audience="memory-api",
    ))
    reader = {"Authorization": "Bearer " + token(private, ["memory:read"])}
    reviewer = {"Authorization": "Bearer " + token(private, ["memory:read", "memory:review"])}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        queue = (await client.get(
            "/v1/memories/review-queue?status=candidate", headers=reviewer)).json()
        mine = [i for i in queue["items"] if "grpc" in i["content"]]
        rejected = await client.post(
            f"/v1/memories/{mine[0]['memory_id']}/reject", headers=reviewer,
            json={"expected_revision": mine[0]["revision"]},
        )
        assert rejected.json()["status"] == "rejected"
        found = (await client.post(
            "/v1/memories/search", headers=reader,
            json={"query": QUERIES["13"], "limit": 5},
        )).json()
        assert found["items"] == []
    await app.state.engine.dispose()
