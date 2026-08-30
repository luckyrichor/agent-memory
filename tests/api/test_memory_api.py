from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient

from agent_memory.api.app import create_app
from agent_memory.config import Settings

TENANT_ID = UUID("30000000-0000-0000-0000-000000000001")
USER_ID = UUID("30000000-0000-0000-0000-000000000002")


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


def bearer_token(private_key: str, *, issuer: str = "memory-test") -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "iss": issuer,
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
