import json
from uuid import uuid4

import jwt
from httpx import ASGITransport, AsyncClient
from test_memory_api import bearer_token, signing_material

from agent_memory.api.app import create_app
from agent_memory.api.schemas import ContextRequest
from agent_memory.config import Settings
from agent_memory.sdk import MemoryClient


async def test_authorized_context_sdk_and_deleted_exclusion(app_database_url):
    private, public = signing_material()
    app = create_app(Settings(database_url=app_database_url, jwt_public_key=public,
                             jwt_issuer="memory-test", jwt_audience="memory-api"))
    token = bearer_token(private)
    headers = {"Authorization": "Bearer " + token}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post("/v1/memories", headers={**headers, "Idempotency-Key": str(uuid4())},
                                    json={"content": "compiler path recovery", "memory_type": "semantic",
                                          "scope": {"kind": "workspace", "workspace_id": "project-a"}})
        assert created.status_code == 201
        packet = await MemoryClient(client, token=token).context(
            ContextRequest(query="compiler", workspace_id="project-a", token_budget=1000))
        assert packet.used_tokens == len(packet.rendered.encode()) <= 1000
        assert json.loads(packet.rendered)["memories"][0]["content"] == "compiler path recovery"
        denied = await client.post("/v1/memories/context", headers=headers,
                                   json={"query": "compiler", "workspace_id": "secret"})
        assert denied.status_code == 403
        invalid = await client.post("/v1/memories/context", headers=headers,
                                    json={"query": "compiler", "token_budget": -1})
        assert invalid.status_code == 422
        claims = jwt.decode(token, options={"verify_signature": False})
        claims["tenant_id"] = str(uuid4())
        other = jwt.encode(claims, private, algorithm="RS256")
        isolated = await MemoryClient(client, token=other).context(ContextRequest(query="compiler"))
        assert isolated.rendered == ""
        record = created.json()
        deleted = await client.post("/v1/deletion-requests", headers={**headers, "Idempotency-Key": str(uuid4())},
                                    json={"memory_id": record["memory_id"], "expected_revision": 1})
        assert deleted.status_code == 202
        packet = await MemoryClient(client, token=token).context(ContextRequest(query="compiler"))
        assert packet.rendered == ""
    await app.state.engine.dispose()
