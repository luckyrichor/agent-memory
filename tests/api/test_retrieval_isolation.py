from datetime import UTC, datetime
from uuid import UUID, uuid4

import jwt
import pytest
from httpx import ASGITransport, AsyncClient
from test_memory_api import bearer_token, signing_material

from agent_memory.api.app import create_app
from agent_memory.config import Settings
from agent_memory.domain.principal import RequestPrincipal
from agent_memory.infrastructure.db import create_session_factory, session_for_principal
from agent_memory.infrastructure.orm import MemoryEmbeddingRow


@pytest.mark.asyncio
async def test_all_channels_filter_tenant_user_workspace_and_status_before_rank(app_database_url):
    private, public = signing_material()
    app = create_app(Settings(database_url=app_database_url, jwt_public_key=public,
        jwt_issuer="memory-test", jwt_audience="memory-api"))
    tenant, user = uuid4(), uuid4()
    base = jwt.decode(bearer_token(private), options={"verify_signature": False})
    vector = [1.0] + [0.0]*1023
    sessions = create_session_factory(app.state.engine)
    def headers(claims):
        return {"Authorization": "Bearer " + jwt.encode(claims, private, algorithm="RS256")}
    caller = {**base, "tenant_id": str(tenant), "sub": str(user), "allowed_workspace_ids": ["public"]}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for name, tid, uid, workspace, scope, memory_type in [
            ("allowed",tenant,user,"public","workspace","semantic"),
            ("tenant",uuid4(),user,"public","workspace","semantic"),
            ("workspace",tenant,user,"private","workspace","semantic"),
            ("user",tenant,uuid4(),None,"user_global","semantic"),
            ("review",tenant,user,None,"tenant","procedural"),
            ("archived",tenant,user,"public","workspace","semantic"),
        ]:
            claims = {**caller, "tenant_id": str(tid), "sub": str(uid),
                      "allowed_workspace_ids": [workspace] if workspace else []}
            scope_body = {"kind": scope}
            if workspace:
                scope_body["workspace_id"] = workspace
            if scope == "user_global":
                scope_body["subject_user_id"] = str(uid)
            response = await client.post("/v1/memories", headers={**headers(claims),
                "Idempotency-Key": str(uuid4())}, json={"content": "compiler " + name,
                "memory_type": memory_type, "scope": scope_body})
            assert response.status_code == 201
            record = response.json()
            principal = RequestPrincipal(tid, uid, frozenset(), frozenset({"memory:write"}),
                                         frozenset([workspace] if workspace else []))
            async with session_for_principal(sessions, principal) as session:
                session.add(MemoryEmbeddingRow(tenant_id=tid, memory_version_id=UUID(record["version_id"]),
                    model="isolation", embedding=vector, updated_at=datetime.now(UTC)))
            if name == "archived":
                response = await client.post(f'/v1/memories/{record["memory_id"]}/archive',
                    headers=headers(claims), json={"expected_revision": 1})
                assert response.status_code == 200
        result = await client.post("/v1/memories/search", headers=headers(caller), json={
            "query": "compiler", "vector": vector, "model": "isolation", "workspace_id": "public"})
        assert result.status_code == 200, result.text
        assert [hit["content"] for hit in result.json()["items"]] == ["compiler allowed"]
        assert result.json()["channel_counts"] == {"lexical": 1, "vector": 1, "structured": 1}
        forbidden = await client.post("/v1/memories/search",
            headers=headers({**caller, "permissions": []}), json={"query": "compiler"})
        assert forbidden.status_code == 403
    await app.state.engine.dispose()
