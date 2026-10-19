"""Mechanical full-import lineage only; fixed extractor is not quality evidence."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from agent_memory.api.app import create_app
from agent_memory.application.extraction_worker import ExtractionWorker
from agent_memory.config import Settings
from agent_memory.domain.enums import AuthorityLevel, MemoryType, ScopeKind, VerificationStatus
from agent_memory.domain.events import MemoryCandidate
from agent_memory.domain.models import MemoryScope
from agent_memory.domain.principal import RequestPrincipal
from agent_memory.evals.api_import import import_conversation
from agent_memory.evals.datasets import Conversation, Document
from agent_memory.evals.evidence_observer import observe_versions
from agent_memory.infrastructure.db import (
    create_engine,
    create_session_factory,
    session_for_principal,
)
from agent_memory.infrastructure.event_repositories import (
    PostgresExtractionBackend,
    PostgresOutboxRepository,
)
from agent_memory.sdk import MemoryClient


class FixedExtractor:
    version = "eval-fixed-v1"

    async def extract(self, event):
        return (
            MemoryCandidate(
                content="Synthetic preference for a blue interface",
                memory_type=MemoryType.SEMANTIC,
                scope=event.draft.scope,
                confidence=0.8,
                utility=0.5,
                authority_level=AuthorityLevel.AGENT_INFERENCE,
                verification_status=VerificationStatus.UNVERIFIED,
            ),
        )


async def test_public_event_import_observes_lineage_without_owner_bypass(app_database_url):
    tenant, user = uuid4(), uuid4()
    principal = RequestPrincipal(
        tenant, user, frozenset(), frozenset({"memory:read", "memory:write"}), frozenset({"eval"})
    )
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = (
        key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    token = jwt.encode(
        {
            "iss": "eval-test",
            "aud": "eval-test",
            "sub": str(user),
            "tenant_id": str(tenant),
            "permissions": ["memory:read", "memory:write"],
            "allowed_workspace_ids": ["eval"],
            "exp": datetime.now(UTC) + timedelta(minutes=5),
        },
        key,
        algorithm="RS256",
    )
    app = create_app(
        Settings(
            database_url=app_database_url,
            jwt_public_key=public,
            jwt_issuer="eval-test",
            jwt_audience="eval-test",
        )
    )
    engine = create_engine(app_database_url)
    sessions = create_session_factory(engine)
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://eval"
        ) as http:
            conv = Conversation(
                conversation_id="synthetic-full",
                questions=[],
                documents=[
                    Document(
                        source_id="s1:t1",
                        session_id="s1",
                        role="user",
                        text="I prefer a blue interface.",
                        occurred_at="2025-01-01T00:00:00+00:00",
                    )
                ],
            )
            mapping = await import_conversation(
                MemoryClient(http, token=token),
                conv,
                MemoryScope(ScopeKind.WORKSPACE, "eval", None),
                mode="full",
            )
        now = lambda: datetime.now(UTC)
        async with session_for_principal(sessions, principal) as session:
            assert (
                await PostgresOutboxRepository(session, new_id=uuid4, now=now).dispatch_once(
                    tenant, 10, "eval-fixed-v1"
                )
                == 1
            )
        worker = ExtractionWorker(
            PostgresExtractionBackend(sessions, new_id=uuid4, now=now),
            FixedExtractor(),
            now=now,
            lease_duration=timedelta(seconds=30),
        )
        assert (await worker.run_once(tenant, "eval-worker")).outcome == "succeeded"
        async with session_for_principal(sessions, principal) as session:
            versions = await observe_versions(session, mapping, tenant_id=tenant)
            assert len(versions) == 1
            assert (
                versions[0]["source_id"] == "s1:t1"
                and versions[0]["event_id"] == mapping[0]["event_id"]
            )
            assert "version_id" in versions[0] and "memory_id" in versions[0]
        other = RequestPrincipal(uuid4(), user, frozenset(), frozenset(), frozenset())
        async with session_for_principal(sessions, other) as session:
            assert await observe_versions(session, mapping, tenant_id=tenant) == []
    finally:
        await app.state.engine.dispose()
        await engine.dispose()
