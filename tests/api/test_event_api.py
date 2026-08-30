from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient

from agent_memory.api.app import create_app
from agent_memory.config import Settings

TENANT_ID = UUID("32000000-0000-0000-0000-000000000001")
USER_ID = UUID("32000000-0000-0000-0000-000000000002")


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


def token(private_key: str, *, workspaces: list[str] | None = None) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "iss": "memory-test",
            "aud": "memory-api",
            "sub": str(USER_ID),
            "tenant_id": str(TENANT_ID),
            "roles": ["developer"],
            "permissions": ["memory:write"],
            "allowed_workspace_ids": workspaces or ["project-a"],
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        private_key,
        algorithm="RS256",
    )


def event_body(*, summary: str = "arm64 build failed") -> dict[str, object]:
    return {
        "events": [
            {
                "idempotency_key": "api-event-1",
                "session_id": "api-session",
                "sequence_number": 1,
                "event_type": "tool.result",
                "agent_id": "coding_agent",
                "occurred_at": "2026-08-30T12:00:00Z",
                "scope": {"kind": "workspace", "workspace_id": "project-a"},
                "payload": {
                    "tool_name": "build",
                    "exit_code": 1,
                    "summary": summary,
                },
            }
        ]
    }


@pytest.mark.asyncio
async def test_event_api_authenticates_binds_tenant_and_replays_idempotently(
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
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        missing = await client.post("/v1/events:batch", json=event_body())
        first = await client.post(
            "/v1/events:batch",
            headers={"Authorization": f"Bearer {token(private_key)}"},
            json=event_body(),
        )
        replay = await client.post(
            "/v1/events:batch",
            headers={"Authorization": f"Bearer {token(private_key)}"},
            json=event_body(),
        )

    assert missing.status_code == 401
    assert first.status_code == 202
    assert first.json()["items"][0]["disposition"] == "accepted"
    assert replay.status_code == 202
    assert replay.json()["items"][0]["disposition"] == "duplicate"
    assert replay.json()["items"][0]["event_id"] == first.json()["items"][0]["event_id"]
    await app.state.engine.dispose()


@pytest.mark.asyncio
async def test_event_api_rejects_tenant_override_and_forbidden_workspace(
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
    forged = event_body()
    forged["tenant_id"] = "42000000-0000-0000-0000-000000000001"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        tenant_override = await client.post(
            "/v1/events:batch",
            headers={"Authorization": f"Bearer {token(private_key)}"},
            json=forged,
        )
        forbidden = await client.post(
            "/v1/events:batch",
            headers={
                "Authorization": f"Bearer {token(private_key, workspaces=['project-b'])}"
            },
            json=event_body(),
        )

    assert tenant_override.status_code == 422
    assert forbidden.status_code == 403
    assert forbidden.json()["error"]["code"] == "EVENT_SCOPE_FORBIDDEN"
    await app.state.engine.dispose()


@pytest.mark.asyncio
async def test_event_api_returns_stable_conflict_for_changed_replay(
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
    headers = {"Authorization": f"Bearer {token(private_key)}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post("/v1/events:batch", headers=headers, json=event_body())
        conflict = await client.post(
            "/v1/events:batch",
            headers=headers,
            json=event_body(summary="changed"),
        )

    assert created.status_code == 202
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "EVENT_IDEMPOTENCY_CONFLICT"
    await app.state.engine.dispose()
