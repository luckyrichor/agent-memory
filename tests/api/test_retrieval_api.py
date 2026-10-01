from datetime import UTC, datetime
from uuid import UUID, uuid4

import jwt
import pytest
from httpx import ASGITransport, AsyncClient
from test_memory_api import USER_ID, bearer_token, signing_material

from agent_memory.api.app import create_app
from agent_memory.config import Settings
from agent_memory.domain.principal import RequestPrincipal
from agent_memory.infrastructure.db import create_session_factory, session_for_principal
from agent_memory.infrastructure.orm import MemoryEmbeddingRow


@pytest.mark.asyncio
async def test_postgres_three_channels_pagination_current_version_and_tombstone(app_database_url):
    private, public = signing_material()
    app = create_app(Settings(database_url=app_database_url, jwt_public_key=public,
        jwt_issuer="memory-test", jwt_audience="memory-api"))
    tenant_id = uuid4()
    claims = jwt.decode(bearer_token(private), options={"verify_signature": False})
    claims["tenant_id"] = str(tenant_id)
    headers = {"Authorization": "Bearer " + jwt.encode(claims, private, algorithm="RS256")}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        ids = []
        for content in ("build failure compiler path missing", "unrelated shopping preferences"):
            response = await client.post("/v1/memories", headers={**headers,
                "Idempotency-Key": str(uuid4())}, json={"content": content,
                "memory_type": "semantic", "scope": {"kind": "workspace", "workspace_id": "project-a"}})
            assert response.status_code == 201
            ids.append(response.json())
        principal = RequestPrincipal(tenant_id, USER_ID, frozenset(),
            frozenset({"memory:read", "memory:write"}), frozenset({"project-a"}))
        async with session_for_principal(create_session_factory(app.state.engine), principal) as session:
            for index, record in enumerate(ids):
                vector = [0.0] * 1536
                vector[index] = 1.0
                session.add(MemoryEmbeddingRow(tenant_id=tenant_id,
                    memory_version_id=UUID(record["version_id"]), model="fixture-semantic-v1",
                    embedding=vector, updated_at=datetime.now(UTC)))
        vector = [1.0] + [0.0] * 1535
        query = {"query": "compiler", "vector": vector, "model": "fixture-semantic-v1",
                 "memory_type": "semantic", "workspace_id": "project-a", "limit": 1}
        result = await client.post("/v1/memories/search", headers=headers, json=query)
        assert result.status_code == 200, result.text
        page = result.json()
        assert page["items"][0]["memory_id"] == ids[0]["memory_id"]
        hit = page["items"][0]
        assert set(hit["ranks"]) == {"lexical", "vector", "structured"}
        assert hit["score"] == pytest.approx(sum(
            (0.25 if channel == "structured" else 1) / (60 + rank)
            for channel, rank in hit["ranks"].items()))
        assert page["channel_counts"]["lexical"] == 1
        assert page["next_offset"] == 1
        second = (await client.post("/v1/memories/search", headers=headers,
            json={**query, "offset": 1})).json()
        assert second["items"][0]["memory_id"] != hit["memory_id"]
        # Fixture supplied query vector deliberately represents a paraphrase; not a real model eval.
        paraphrase = (await client.post("/v1/memories/search", headers=headers,
            json={**query, "query": "toolchain executable unavailable"})).json()
        assert paraphrase["channel_counts"]["lexical"] == 0
        assert paraphrase["items"][0]["memory_id"] == ids[0]["memory_id"]
        correction = await client.post(f'/v1/memories/{ids[0]["memory_id"]}/versions',
            headers=headers, json={"expected_revision": 1, "content": "fixed compiler",
                                   "reason": "test"})
        assert correction.status_code == 201
        stale = (await client.post("/v1/memories/search", headers=headers, json=query)).json()
        assert stale["channel_counts"]["vector"] == 1
        assert stale["items"][0]["content"] == "fixed compiler"
        versions = (await client.get(f'/v1/memories/{ids[0]["memory_id"]}/versions?limit=1',
                                    headers=headers)).json()
        assert len(versions["items"]) == 1 and versions["next_offset"] == 1
        final_versions = (await client.get(
            f'/v1/memories/{ids[0]["memory_id"]}/versions?limit=1&offset=1', headers=headers)).json()
        assert final_versions["items"][0]["content"] == "fixed compiler"
        assert final_versions["next_offset"] is None
        deleted = await client.post("/v1/deletion-requests", headers={**headers,
            "Idempotency-Key": str(uuid4())}, json={"memory_id": ids[0]["memory_id"], "expected_revision": 2})
        assert deleted.status_code == 202
        after = (await client.post("/v1/memories/search", headers=headers, json=query)).json()
        assert all(hit["memory_id"] != ids[0]["memory_id"] for hit in after["items"])
        forbidden = await client.post("/v1/memories/search", headers=headers,
            json={**query, "workspace_id": "secret"})
        assert forbidden.status_code == 403
        forged = await client.post("/v1/memories/search", headers=headers,
            json={**query, "tenant_id": str(uuid4())})
        assert forged.status_code == 422
        invalid = await client.post("/v1/memories/search", headers=headers,
            json={**query, "vector": [0.0]*1536})
        assert invalid.status_code == 422
    await app.state.engine.dispose()
