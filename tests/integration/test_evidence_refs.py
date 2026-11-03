"""E1: search and context cite the source events of a memory (ids + the caller's coordinates)."""
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from test_candidate_dedup import NOW, TEXT, USER_ID, run_event

from agent_memory.api.app import create_app
from agent_memory.api.schemas import ContextRequest, SearchRequest
from agent_memory.application.context_builder import MemoryContextBuilder
from agent_memory.application.retrieval import MemoryRetriever, RetrievalQuery
from agent_memory.config import Settings
from agent_memory.domain.principal import RequestPrincipal
from agent_memory.infrastructure.db import (
    create_engine,
    create_session_factory,
    session_for_principal,
)
from agent_memory.infrastructure.orm import EventRow, EvidenceRow
from agent_memory.infrastructure.retrieval import PostgresCandidateProvider
from agent_memory.sdk import MemoryClient

QUERY = "protobuf arm64 dependency conflict pinning"
REF_KEYS = {"event_id", "role", "event_type", "occurred_at", "session_id", "sequence_number"}


def reader(tenant_id: UUID) -> RequestPrincipal:
    return RequestPrincipal(
        tenant_id, USER_ID, frozenset({"developer"}), frozenset({"memory:read"}),
        frozenset({"project-a"}),
    )


async def seed_evidence(sessions: object, tenant_id: UUID, events: int) -> None:
    """One origin event, then (events - 1) later events repeating the same text (E2 -> supports)."""
    for number in range(events):
        await run_event(sessions, tenant_id, f"ev-{number}", TEXT)


@pytest.mark.asyncio
async def test_hits_carry_capped_ordered_references_and_context_cites_them(
    app_database_url: str,
) -> None:
    tenant_id = uuid4()
    engine = create_engine(app_database_url)
    sessions = create_session_factory(engine)
    try:
        await seed_evidence(sessions, tenant_id, events=7)  # 1 origin + 6 supports
        async with session_for_principal(sessions, reader(tenant_id)) as session:
            provider = PostgresCandidateProvider(session)
            page = await MemoryRetriever(provider).search(
                RetrievalQuery(QUERY, workspace_id="project-a"), reader(tenant_id))
            assert len(page.items) == 1
            hit = page.items[0]
            assert hit.evidence_total == 7 and len(hit.evidence) == 5  # capped, total kept
            assert hit.evidence[0].role == "triggered_by"  # origin survives the cap
            assert {ref.role for ref in hit.evidence[1:]} == {"supports"}
            origin = hit.evidence[0]
            assert (origin.session_id, origin.sequence_number) == ("e2-session-ev-0", 1)
            assert (origin.event_type, origin.occurred_at) == ("tool.result", NOW)

            # context: compact, capped at 3, total preserved, trust label unchanged
            packet = MemoryContextBuilder().build(page.items, 100000)
            entry = json.loads(packet.rendered)["memories"][0]
            assert len(entry["evidence_refs"]) == 3 and entry["evidence_total"] == 7
            assert set(entry["evidence_refs"][0]) == {"event_id", "role"}
            assert entry["evidence_refs"][0]["role"] == "triggered_by"
            assert entry["evidence_refs"][0]["event_id"] == str(origin.event_id)
            assert "e2-session" not in packet.rendered  # session names stay out of the prompt
            assert entry["trust"] == "unverified_historical_reference"

            # another tenant cannot read these references even with the right version id
            assert await provider.evidence([hit.version_id], reader(uuid4()), 5) == {}
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_contradicting_and_verifying_evidence_outrank_plain_support_under_the_cap(
    app_database_url: str,
) -> None:
    tenant_id = uuid4()
    engine = create_engine(app_database_url)
    sessions = create_session_factory(engine)
    try:
        await seed_evidence(sessions, tenant_id, events=7)  # origin ev-0, supports ev-1..ev-6
        async with session_for_principal(sessions, reader(tenant_id)) as session:
            page = await MemoryRetriever(PostgresCandidateProvider(session)).search(
                RetrievalQuery(QUERY, workspace_id="project-a"), reader(tenant_id))
            version_id = page.items[0].version_id
            late = {
                number: await session.scalar(select(EventRow.event_id).where(
                    EventRow.session_id == f"e2-session-ev-{number}"))
                for number in (5, 6)
            }
            # the LAST events (largest ids) also contradict / verify the same version
            for number, role in ((6, "contradicts"), (5, "verified_by")):
                session.add(EvidenceRow(tenant_id=tenant_id, memory_version_id=version_id,
                                        event_id=late[number], role=role, created_at=NOW))
        async with session_for_principal(sessions, reader(tenant_id)) as session:
            page = await MemoryRetriever(PostgresCandidateProvider(session)).search(
                RetrievalQuery(QUERY, workspace_id="project-a"), reader(tenant_id))
            hit = page.items[0]
            assert hit.evidence_total == 9 and len(hit.evidence) == 5
            assert [ref.role for ref in hit.evidence] == [
                "triggered_by", "contradicts", "verified_by", "supports", "supports"]
            assert hit.evidence[1].event_id == late[6]  # the cap kept the late contradiction
    finally:
        await engine.dispose()


def signing_material() -> tuple[str, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption()).decode()
    public = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    return private, public


def token_for(private_key: str, tenant_id: UUID) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {"iss": "memory-test", "aud": "memory-api", "sub": str(USER_ID),
         "tenant_id": str(tenant_id), "roles": ["developer"],
         "permissions": ["memory:read", "memory:write"],
         "allowed_workspace_ids": ["project-a"], "iat": now, "exp": now + timedelta(minutes=5)},
        private_key, algorithm="RS256")


@pytest.mark.asyncio
async def test_http_search_and_sdk_expose_references_but_never_event_content(
    app_database_url: str,
) -> None:
    tenant_id = uuid4()
    private, public = signing_material()
    app = create_app(Settings(database_url=app_database_url, jwt_public_key=public,
                             jwt_issuer="memory-test", jwt_audience="memory-api"))
    sessions = create_session_factory(app.state.engine)
    token = token_for(private, tenant_id)
    headers = {"Authorization": "Bearer " + token}
    try:
        await seed_evidence(sessions, tenant_id, events=2)  # origin + one supports
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            explicit = await client.post(
                "/v1/memories", headers={**headers, "Idempotency-Key": str(uuid4())},
                json={"content": "hand written quokka note", "memory_type": "semantic",
                      "scope": {"kind": "workspace", "workspace_id": "project-a"}})
            assert explicit.status_code == 201

            raw = await client.post("/v1/memories/search", headers=headers,
                                    json={"query": QUERY, "workspace_id": "project-a"})
            assert raw.status_code == 200
            item = next(i for i in raw.json()["items"] if TEXT in i["content"])
            assert item["evidence_total"] == 2
            assert [ref["role"] for ref in item["evidence"]] == ["triggered_by", "supports"]
            assert all(set(ref) == REF_KEYS for ref in item["evidence"])  # no payload fields
            assert TEXT not in json.dumps(item["evidence"])

            # explicit writes have no source events: empty means "none recorded"
            quokka = await client.post("/v1/memories/search", headers=headers,
                                       json={"query": "quokka", "workspace_id": "project-a"})
            note = quokka.json()["items"][0]
            assert note["evidence"] == [] and note["evidence_total"] == 0

            # SDK parses the same fields; context cites them
            client_sdk = MemoryClient(client, token=token)
            found = await client_sdk.search(SearchRequest(query=QUERY, workspace_id="project-a"))
            assert found.items[0].evidence[0].role == "triggered_by"
            assert found.items[0].evidence_total == 2
            packet = await client_sdk.context(
                ContextRequest(query=QUERY, workspace_id="project-a", token_budget=2000))
            cited = json.loads(packet.rendered)["memories"][0]
            assert [ref["role"] for ref in cited["evidence_refs"]] == ["triggered_by", "supports"]

            # another tenant sees nothing, hence no references either
            other = await client.post(
                "/v1/memories/search", headers={"Authorization": "Bearer " + token_for(private, uuid4())},
                json={"query": QUERY, "workspace_id": "project-a"})
            assert other.status_code == 200 and other.json()["items"] == []
    finally:
        await app.state.engine.dispose()
