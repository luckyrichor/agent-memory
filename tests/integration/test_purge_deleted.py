"""D3 / LC7: logically deleted memories must be physically erasable (text + vectors)."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text

from agent_memory.api.app import create_app
from agent_memory.application.embedding import EmbeddingWorker
from agent_memory.config import Settings
from agent_memory.domain.principal import RequestPrincipal
from agent_memory.infrastructure.db import (
    create_engine,
    create_session_factory,
    session_for_principal,
)
from agent_memory.infrastructure.embedding import FixtureEmbeddingProvider, PostgresEmbeddingBackend
from agent_memory.infrastructure.orm import (
    AuditLogRow,
    JobRow,
    MemoryEmbeddingRow,
    MemoryVersionRow,
)
from agent_memory.infrastructure.purge import PURGED_CONTENT_HASH, purge_deleted_memories

USER_ID = UUID("3a000000-0000-0000-0000-000000000002")
SCOPE = {"kind": "workspace", "workspace_id": "project-a"}
DOOMED_TEXT = "quetzal-ledger-tangerine deployment checklist"
KEPT_TEXT = "marmot-harbor-cinnamon rollback notes"
OTHER_TENANT_TEXT = "ocelot-vault-pepper billing export"


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


def headers_for(private: str, tenant_id: UUID) -> dict[str, str]:
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "iss": "memory-test", "aud": "memory-api", "sub": str(USER_ID),
            "tenant_id": str(tenant_id), "roles": ["developer"],
            "permissions": ["memory:read", "memory:write", "memory:delete"],
            "allowed_workspace_ids": ["project-a"], "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        private, algorithm="RS256",
    )
    return {"Authorization": f"Bearer {token}"}


def principal(tenant_id: UUID) -> RequestPrincipal:
    return RequestPrincipal(
        tenant_id, USER_ID, frozenset(), frozenset({"memory:read"}), frozenset({"project-a"})
    )


async def remember(client: AsyncClient, headers: dict[str, str], content: str) -> dict[str, object]:
    response = await client.post(
        "/v1/memories", headers={**headers, "Idempotency-Key": str(uuid4())},
        json={"content": content, "memory_type": "semantic", "scope": SCOPE},
    )
    assert response.status_code == 201, response.text
    body: dict[str, object] = response.json()
    return body


async def delete(client: AsyncClient, headers: dict[str, str], created: dict[str, object]) -> None:
    response = await client.post(
        "/v1/deletion-requests", headers={**headers, "Idempotency-Key": str(uuid4())},
        json={"memory_id": created["memory_id"], "expected_revision": created["revision"]},
    )
    assert response.status_code == 202, response.text


@pytest.mark.asyncio
async def test_purge_erases_text_and_vectors_of_deleted_memories_only(
    app_database_url: str,
) -> None:
    private, public = keys()
    app = create_app(
        Settings(
            database_url=app_database_url, jwt_public_key=public,
            jwt_issuer="memory-test", jwt_audience="memory-api",
        )
    )
    tenant_a, tenant_b = uuid4(), uuid4()
    headers_a, headers_b = headers_for(private, tenant_a), headers_for(private, tenant_b)
    engine = create_engine(app_database_url)
    sessions = create_session_factory(engine)
    counter = iter(range(1, 10_000))

    def new_id() -> UUID:
        return UUID(f"3a100000-0000-0000-0000-{next(counter):012d}")

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),  # type: ignore[arg-type]
            base_url="http://memory",
        ) as client:
            doomed = await remember(client, headers_a, DOOMED_TEXT)
            kept = await remember(client, headers_a, KEPT_TEXT)
            other = await remember(client, headers_b, OTHER_TENANT_TEXT)
            await delete(client, headers_a, doomed)
            await delete(client, headers_b, other)
            doomed_version = UUID(str(doomed["version_id"]))
            kept_version = UUID(str(kept["version_id"]))
            other_version = UUID(str(other["version_id"]))

            # A vector for the doomed version and for tenant B's deleted one.
            for tenant, version in ((tenant_a, doomed_version), (tenant_b, other_version)):
                async with session_for_principal(sessions, principal(tenant)) as session:
                    session.add(
                        MemoryEmbeddingRow(
                            tenant_id=tenant, memory_version_id=version,
                            model="fixture-semantic-v1", embedding=[1.0] + [0.0] * 1023,
                            updated_at=datetime.now(UTC),
                        )
                    )

            async def snapshot(tenant: UUID, version: UUID) -> tuple[str, str, int, str]:
                async with session_for_principal(sessions, principal(tenant)) as session:
                    content, content_hash = (
                        await session.execute(
                            select(MemoryVersionRow.content, MemoryVersionRow.content_hash)
                            .where(MemoryVersionRow.memory_version_id == version)
                        )
                    ).one()
                    lexical = await session.scalar(
                        text("SELECT lexical_en::text FROM memory_versions "
                             "WHERE memory_version_id = :v"), {"v": version},
                    )
                    vectors = len((await session.scalars(
                        select(MemoryEmbeddingRow.memory_version_id)
                        .where(MemoryEmbeddingRow.memory_version_id == version)
                    )).all())
                return content, content_hash, vectors, str(lexical)

            async def job_status(tenant: UUID, version: UUID) -> tuple[str, str | None]:
                async with session_for_principal(sessions, principal(tenant)) as session:
                    job = (await session.scalars(
                        select(JobRow).where(
                            JobRow.job_type == "embed_memory",
                            JobRow.payload["version_id"].astext == str(version),
                        )
                    )).one()
                    return job.status, job.last_error_code

            future = datetime.now(UTC) + timedelta(days=31)
            common = {"older_than": timedelta(days=30), "new_id": new_id}

            # Before: the text is there, in the table and in the generated lexical vector.
            content, _, vectors, lexical = await snapshot(tenant_a, doomed_version)
            assert content == DOOMED_TEXT and vectors == 1 and "quetzal" in lexical
            assert await job_status(tenant_a, doomed_version) == ("pending", None)

            # Retention not reached: nothing is eligible even with execute=True.
            young = await purge_deleted_memories(
                sessions, tenant_a, now=datetime.now(UTC), execute=True, **common  # type: ignore[arg-type]
            )
            assert (young.memories, young.versions, young.embeddings) == (0, 0, 0)
            assert (await snapshot(tenant_a, doomed_version))[0] == DOOMED_TEXT

            # Dry run reports what would happen and changes nothing.
            dry = await purge_deleted_memories(
                sessions, tenant_a, now=future, **common  # type: ignore[arg-type]
            )
            assert dry == type(dry)(
                executed=False, memories=1, versions=1, embeddings=1, jobs_stopped=1
            )
            assert (await snapshot(tenant_a, doomed_version))[0] == DOOMED_TEXT

            # Execute.
            done = await purge_deleted_memories(
                sessions, tenant_a, now=future, execute=True, **common  # type: ignore[arg-type]
            )
            assert done == type(done)(
                executed=True, memories=1, versions=1, embeddings=1, jobs_stopped=1
            )
            content, content_hash, vectors, lexical = await snapshot(tenant_a, doomed_version)
            assert content == "" and content_hash == PURGED_CONTENT_HASH
            assert vectors == 0 and "quetzal" not in lexical and lexical == ""
            assert await job_status(tenant_a, doomed_version) == ("dead", "MEMORY_PURGED")

            # The live memory of the same tenant and the other tenant's deleted memory are intact.
            assert (await snapshot(tenant_a, kept_version))[0] == KEPT_TEXT
            assert await job_status(tenant_a, kept_version) == ("pending", None)
            other_content, _, other_vectors, _ = await snapshot(tenant_b, other_version)
            assert other_content == OTHER_TENANT_TEXT and other_vectors == 1

            # Audit trail records the purge without text.
            async with session_for_principal(sessions, principal(tenant_a)) as session:
                audits = (await session.scalars(
                    select(AuditLogRow).where(AuditLogRow.action == "memory.purge")
                )).all()
            assert [a.resource_id for a in audits] == [UUID(str(doomed["memory_id"]))]
            assert DOOMED_TEXT not in str(audits[0].metadata_json)

            # Idempotent.
            again = await purge_deleted_memories(
                sessions, tenant_a, now=future, execute=True, **common  # type: ignore[arg-type]
            )
            assert (again.memories, again.versions, again.embeddings) == (0, 0, 0)

            # A worker cannot bring the vector back: the stopped job is never claimed, and the
            # live memory still gets its vector.
            worker = EmbeddingWorker(
                PostgresEmbeddingBackend(sessions), FixtureEmbeddingProvider(),
                timeout=5, lease_seconds=30,
            )
            while (await worker.run_once(tenant_a, "d3-worker")).outcome != "no_job":
                pass
            assert (await snapshot(tenant_a, doomed_version))[2] == 0
            assert (await snapshot(tenant_a, kept_version))[2] == 1

            # Search no longer finds the erased text: zero lexical hits, and the erased memory is
            # not returned by any channel. (The live memory may still come back through the
            # structured channel, which only filters by workspace, so check hits, not item count.)
            for query, lexical_hits in (("quetzal", 0), ("marmot", 1)):
                found = await client.post(
                    "/v1/memories/search", headers=headers_a,
                    json={"query": query, "workspace_id": "project-a"},
                )
                assert found.status_code == 200, found.text
                body = found.json()
                assert body["channel_counts"]["lexical"] == lexical_hits, (query, body)
                assert str(doomed["memory_id"]) not in {i["memory_id"] for i in body["items"]}
                assert DOOMED_TEXT not in found.text
    finally:
        await app.state.engine.dispose()  # type: ignore[attr-defined]
        await engine.dispose()
