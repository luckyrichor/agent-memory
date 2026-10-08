import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest

from agent_memory.application.embedding import EmbeddingWorker
from agent_memory.infrastructure.embedding import FixtureEmbeddingProvider, HTTPEmbeddingProvider
from agent_memory.infrastructure.in_memory_embedding import InMemoryEmbeddingBackend


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", [float("nan"), 0.0])
async def test_retry_dead_letter_remains_rebuildable_and_tenant_isolated(invalid: float) -> None:
    backend = InMemoryEmbeddingBackend()
    tenant, version = uuid4(), uuid4()
    now = datetime.now(UTC)
    await backend.enqueue(tenant, version, "content", now)

    class InvalidProvider(FixtureEmbeddingProvider):
        async def embed(self, content: str) -> list[float]:
            return [invalid] * 1024

    worker = EmbeddingWorker(backend, InvalidProvider())
    assert (await worker.run_once(uuid4(), "other", now=now)).outcome == "no_job"
    for step, outcome in enumerate(["retry_wait", "retry_wait", "dead"]):
        result = await worker.run_once(tenant, "w", now=now + timedelta(seconds=step * 400))
        assert result.outcome == outcome
    assert len(backend.jobs) == 1 and backend.vectors == {}
    await backend.rebuild(tenant, version, "new", now)
    good = EmbeddingWorker(backend, FixtureEmbeddingProvider())
    assert (await good.run_once(tenant, "w", now=now)).outcome == "succeeded"
    assert len(backend.jobs) == 2
    assert len(backend.vectors[tenant, version][1]) == 1024


@pytest.mark.asyncio
async def test_http_provider_protocol_and_timeout_are_under_caller_control() -> None:
    def endpoint(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer test-token"
        assert b'"model":"test-model"' in request.content
        return httpx.Response(200, json={"data": [{"embedding": [0.25] * 1024}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(endpoint), timeout=1) as client:
        provider = HTTPEmbeddingProvider(
            client, endpoint="https://embedding.test/v1", model="test-model", token="test-token"
        )
        assert await provider.embed("content") == [0.25] * 1024


@pytest.mark.asyncio
async def test_ark_protocol_uses_requested_dimensions_and_dictionary_response() -> None:
    def endpoint(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer test-token"
        assert json.loads(request.content) == {
            "model": "ark-model",
            "input": [{"type": "text", "text": "content"}],
            "dimensions": 1024,
            "encoding_format": "float",
        }
        return httpx.Response(200, json={"data": {"embedding": [0.25] * 1024}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(endpoint)) as client:
        provider = HTTPEmbeddingProvider(
            client,
            endpoint="https://embedding.test/v1",
            model="ark-model",
            token="test-token",
            protocol="ark",
        )
        assert await provider.embed("content") == [0.25] * 1024


@pytest.mark.parametrize("bad", ["html", "dimensions"])
async def test_bad_200_then_good_response_retries_and_succeeds(bad):
    backend = InMemoryEmbeddingBackend()
    tenant, version = uuid4(), uuid4()
    now = datetime.now(UTC)
    await backend.enqueue(tenant, version, "content", now)
    calls = 0

    def reply(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return (
                httpx.Response(200, text="<html>bad gateway</html>")
                if bad == "html"
                else httpx.Response(200, json={"data": [{"embedding": [1.0]}]})
            )
        return httpx.Response(200, json={"data": [{"embedding": [1.0] * 1024}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
        worker = EmbeddingWorker(
            backend,
            HTTPEmbeddingProvider(
                client, endpoint="https://test.invalid", model="fixture", token="fixture"
            ),
        )
        assert (await worker.run_once(tenant, "w", now=now)).outcome == "retry_wait"
        assert (
            await worker.run_once(tenant, "w", now=now + timedelta(seconds=10))
        ).outcome == "succeeded"
    assert calls == 2
