"""B4: an exhausted connection pool must fail fast with 503, not hang 30 s into an opaque 500."""
import time
from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from agent_memory.api.app import create_app
from agent_memory.config import Settings

TENANT = UUID("38000000-0000-0000-0000-000000000001")
USER = UUID("38000000-0000-0000-0000-000000000002")


def keys() -> tuple[str, str]:
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return (
        private.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode(),
        private.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        ).decode(),
    )


def bearer(private: str) -> dict[str, str]:
    now = datetime.now(UTC)
    token = jwt.encode(
        {"iss": "t", "aud": "a", "sub": str(USER), "tenant_id": str(TENANT), "roles": [],
         "permissions": ["memory:read"], "allowed_workspace_ids": [], "iat": now,
         "exp": now + timedelta(minutes=5)},
        private, algorithm="RS256",
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_exhausted_pool_returns_503_quickly_and_recovers(app_database_url: str) -> None:
    private, public = keys()
    app = create_app(Settings(
        database_url=app_database_url, jwt_public_key=public, jwt_issuer="t", jwt_audience="a",
        db_pool_size=1, db_max_overflow=0, db_pool_timeout_seconds=0.3,
    ))
    body = {"query": "anything", "limit": 5}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        held = await app.state.engine.connect()  # the only connection is busy
        try:
            started = time.monotonic()
            response = await client.post("/v1/memories/search", headers=bearer(private), json=body)
            elapsed = time.monotonic() - started
        finally:
            await held.close()
        assert response.status_code == 503
        error = response.json()["error"]
        assert error["code"] == "SERVICE_OVERLOADED" and error["retryable"] is True
        assert response.headers["Retry-After"] == "1"
        assert error["request_id"] == response.headers["X-Request-Id"]
        assert elapsed < 2.0, elapsed  # used to be 30 s

        ok = await client.post("/v1/memories/search", headers=bearer(private), json=body)
        assert ok.status_code == 200  # pool recovers once the connection is released
    await app.state.engine.dispose()


@pytest.mark.asyncio
async def test_statement_timeout_is_applied_to_every_connection(app_database_url: str) -> None:
    _, public = keys()
    app = create_app(Settings(
        database_url=app_database_url, jwt_public_key=public, jwt_issuer="t", jwt_audience="a",
        db_statement_timeout_ms=1234,
    ))
    async with app.state.engine.connect() as connection:
        assert (await connection.execute(text("SHOW statement_timeout"))).scalar() == "1234ms"
        with pytest.raises(Exception, match="statement timeout"):
            await connection.execute(text("SET LOCAL statement_timeout = 50"))
            await connection.execute(text("SELECT pg_sleep(1)"))
    await app.state.engine.dispose()
