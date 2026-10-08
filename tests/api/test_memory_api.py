from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient

from agent_memory.api.app import create_app, create_app_from_env
from agent_memory.config import Settings

TENANT_ID = UUID("30000000-0000-0000-0000-000000000001")
USER_ID = UUID("30000000-0000-0000-0000-000000000002")


@pytest.mark.asyncio
async def test_environment_factory_exposes_uvicorn_entrypoint() -> None:
    app = create_app_from_env()

    assert app.title == "Agent Memory"
    assert app.version == "1.0.0"
    await app.state.engine.dispose()


def signing_material() -> tuple[str, str]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    public_pem = (
        private_key.public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    return private_pem, public_pem


def bearer_token(private_key: str, *, issuer: str = "memory-test") -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "iss": issuer,
            "aud": "memory-api",
            "sub": str(USER_ID),
            "tenant_id": str(TENANT_ID),
            "roles": ["developer"],
            "permissions": [
                "memory:read",
                "memory:write",
                "memory:delete",
                "memory:archive",
                "memory:supersede",
                "memory:restore",
                "memory:invalidate",
            ],
            "allowed_workspace_ids": ["project-a"],
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        private_key,
        algorithm="RS256",
    )


@pytest.mark.asyncio
async def test_api_authenticates_and_binds_tenant_from_token(app_database_url: str) -> None:
    private_key, public_key = signing_material()
    app = create_app(
        Settings(
            database_url=app_database_url,
            jwt_public_key=public_key,
            jwt_issuer="memory-test",
            jwt_audience="memory-api",
        )
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        missing = await client.post("/v1/memories", json={})
        assert missing.status_code == 401
        assert missing.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"

        response = await client.post(
            "/v1/memories",
            headers={
                "Authorization": f"Bearer {bearer_token(private_key)}",
                "Idempotency-Key": "api-remember-1",
            },
            json={
                "content": "项目 A 使用 Java 17",
                "memory_type": "semantic",
                "scope": {"kind": "workspace", "workspace_id": "project-a"},
            },
        )

    assert response.status_code == 201
    assert response.json()["status"] == "active"
    assert response.json()["tenant_id"] == str(TENANT_ID)
    await app.state.engine.dispose()


@pytest.mark.asyncio
async def test_request_body_cannot_choose_tenant(app_database_url: str) -> None:
    private_key, public_key = signing_material()
    app = create_app(
        Settings(
            database_url=app_database_url,
            jwt_public_key=public_key,
            jwt_issuer="memory-test",
            jwt_audience="memory-api",
        )
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/v1/memories",
            headers={
                "Authorization": f"Bearer {bearer_token(private_key)}",
                "Idempotency-Key": "api-remember-2",
            },
            json={
                "tenant_id": "40000000-0000-0000-0000-000000000001",
                "content": "forged tenant",
                "memory_type": "semantic",
                "scope": {"kind": "workspace", "workspace_id": "project-a"},
            },
        )

    assert response.status_code == 422
    await app.state.engine.dispose()


@pytest.mark.asyncio
async def test_memory_lifecycle_routes_preserve_versions_and_disable_reads(
    app_database_url: str,
) -> None:
    private_key, public_key = signing_material()
    app = create_app(
        Settings(
            database_url=app_database_url,
            jwt_public_key=public_key,
            jwt_issuer="memory-test",
            jwt_audience="memory-api",
        )
    )
    headers = {
        "Authorization": f"Bearer {bearer_token(private_key)}",
        "Idempotency-Key": "api-lifecycle-1",
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post(
            "/v1/memories",
            headers=headers,
            json={
                "content": "项目 A 使用 Java 17",
                "memory_type": "semantic",
                "scope": {"kind": "workspace", "workspace_id": "project-a"},
            },
        )
        memory_id = created.json()["memory_id"]

        corrected = await client.post(
            f"/v1/memories/{memory_id}/versions",
            headers={"Authorization": headers["Authorization"]},
            json={
                "expected_revision": 1,
                "content": "项目 A 已升级为 Java 21",
                "reason": "user_correction",
            },
        )
        versions = await client.get(
            f"/v1/memories/{memory_id}/versions",
            headers={"Authorization": headers["Authorization"]},
        )
        deleted = await client.post(
            "/v1/deletion-requests",
            headers={"Authorization": headers["Authorization"], "Idempotency-Key": "delete-1"},
            json={"memory_id": memory_id, "expected_revision": 2},
        )
        after_delete = await client.get(
            f"/v1/memories/{memory_id}",
            headers={"Authorization": headers["Authorization"]},
        )

    assert corrected.status_code == 201
    assert corrected.json()["revision"] == 2
    assert versions.status_code == 200
    assert [item["content"] for item in versions.json()["items"]] == [
        "项目 A 使用 Java 17",
        "项目 A 已升级为 Java 21",
    ]
    assert deleted.status_code == 202
    assert deleted.json()["retrieval_disabled"] is True
    assert after_delete.status_code == 404
    await app.state.engine.dispose()


@pytest.mark.asyncio
async def test_sdk_full_lifecycle_and_delete_replays(app_database_url: str) -> None:
    import asyncio

    from agent_memory.domain.enums import MemoryType, ScopeKind
    from agent_memory.domain.models import MemoryScope
    from agent_memory.sdk import MemoryAPIError, MemoryClient

    private, public = signing_material()
    app = create_app(
        Settings(
            database_url=app_database_url,
            jwt_public_key=public,
            jwt_issuer="memory-test",
            jwt_audience="memory-api",
        )
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
            sdk = MemoryClient(http, token=bearer_token(private))
            scope = MemoryScope(ScopeKind.WORKSPACE, "project-a", None)
            created = await sdk.remember(
                "original", MemoryType.SEMANTIC, scope, idempotency_key="sdk-m2-create"
            )
            assert (await sdk.get(created.memory_id)).content == "original"
            corrected = await sdk.correct(created.memory_id, expected_revision=1, content="new")
            assert corrected.revision == 2
            assert (await sdk.get(created.memory_id)).content == "new"
            deletes = await asyncio.gather(
                *[
                    sdk.delete(created.memory_id, expected_revision=2, idempotency_key="sdk-delete")
                    for _ in range(3)
                ]
            )
            assert deletes[0] == deletes[1] == deletes[2]
            assert (
                await sdk.delete(
                    created.memory_id, expected_revision=2, idempotency_key="sdk-delete"
                )
                == deletes[0]
            )
            with pytest.raises(MemoryAPIError) as conflict:
                await sdk.delete(
                    created.memory_id, expected_revision=3, idempotency_key="sdk-delete"
                )
            assert conflict.value.status_code == 409
            with pytest.raises(MemoryAPIError) as missing:
                await sdk.get(created.memory_id)
            assert missing.value.status_code == 404
            for action in ("archive", "supersede"):
                m = await sdk.remember(
                    action, MemoryType.SEMANTIC, scope, idempotency_key=f"sdk-{action}"
                )
                kwargs = {}
                if action == "supersede":
                    replacement = await sdk.remember(
                        "replacement", MemoryType.SEMANTIC, scope, idempotency_key="sdk-successor"
                    )
                    kwargs["successor_id"] = replacement.memory_id
                result = await getattr(sdk, action)(m.memory_id, expected_revision=1, **kwargs)
                assert (
                    result.status.value
                    == {"archive": "archived", "supersede": "superseded"}[action]
                )
                with pytest.raises(MemoryAPIError):
                    await sdk.get(m.memory_id)
                with pytest.raises(MemoryAPIError) as stale:
                    await getattr(sdk, action)(m.memory_id, expected_revision=1, **kwargs)
                assert stale.value.status_code == 409
    finally:
        await app.state.engine.dispose()


async def test_sdk_covers_all_business_routes_and_pagination(app_database_url: str) -> None:
    from uuid import uuid4

    from agent_memory.api.event_schemas import EventBatchRequest
    from agent_memory.api.schemas import SearchRequest
    from agent_memory.domain.enums import MemoryType, ScopeKind
    from agent_memory.domain.models import MemoryScope
    from agent_memory.sdk import MemoryClient

    private, public = signing_material()
    app = create_app(
        Settings(
            database_url=app_database_url,
            jwt_public_key=public,
            jwt_issuer="memory-test",
            jwt_audience="memory-api",
        )
    )
    called = set()

    def record(request):
        import re

        path = re.sub(
            r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", "{memory_id}", request.url.path
        )
        called.add((request.method, path))

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            event_hooks={"request": [_async_hook(record)]},
        ) as http:
            sdk = MemoryClient(http, token=bearer_token(private))
            m = await sdk.remember(
                "SDK contract Java17",
                MemoryType.SEMANTIC,
                MemoryScope(ScopeKind.WORKSPACE, "project-a", None),
                idempotency_key=str(uuid4()),
            )
            await sdk.get(m.memory_id)
            await sdk.correct(
                m.memory_id, expected_revision=1, content="SDK contract Java21", reason="upgrade"
            )
            versions = [v async for v in sdk.iter_versions(m.memory_id, page_size=1)]
            assert [v.reason for v in versions] == [None, "upgrade"]
            await sdk.archive(m.memory_id, expected_revision=2)
            await sdk.restore(m.memory_id, expected_revision=3)
            await sdk.invalidate(m.memory_id, expected_revision=4)
            successor = await sdk.remember(
                "successor",
                MemoryType.SEMANTIC,
                MemoryScope(ScopeKind.WORKSPACE, "project-a", None),
                idempotency_key=str(uuid4()),
            )
            await sdk.supersede(m.memory_id, expected_revision=5, successor_id=successor.memory_id)
            assert (await sdk.lifecycle(m.memory_id)).successor_id == successor.memory_id
            await sdk.delete(m.memory_id, expected_revision=6, idempotency_key=str(uuid4()))
            assert [v async for v in sdk.iter_search(SearchRequest(query="successor"))]
            event = EventBatchRequest.model_validate(
                {
                    "events": [
                        {
                            "idempotency_key": str(uuid4()),
                            "session_id": str(uuid4()),
                            "sequence_number": 1,
                            "event_type": "tool.result",
                            "agent_id": "sdk",
                            "occurred_at": datetime.now(UTC).isoformat(),
                            "scope": {"kind": "workspace", "workspace_id": "project-a"},
                            "payload": {
                                "tool_name": "build",
                                "exit_code": 0,
                                "summary": "build completed",
                            },
                        }
                    ]
                }
            )
            assert len((await sdk.ingest_events(event)).items) == 1
        routes = {
            (method.upper(), path)
            for path, operations in app.openapi()["paths"].items()
            for method in operations
            if path.startswith("/v1/")
        }
        assert called == routes
    finally:
        await app.state.engine.dispose()


def _async_hook(callback):
    async def hook(request):
        callback(request)

    return hook
