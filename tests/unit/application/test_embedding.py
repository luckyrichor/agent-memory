from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest

from agent_memory.application.embedding import EmbeddingWorker
from agent_memory.infrastructure.embedding import FixtureEmbeddingProvider, HTTPEmbeddingProvider
from agent_memory.infrastructure.in_memory_embedding import InMemoryEmbeddingBackend


@pytest.mark.asyncio
async def test_retry_dead_letter_remains_rebuildable_and_tenant_isolated() -> None:
    backend = InMemoryEmbeddingBackend()
    tenant, version = uuid4(), uuid4()
    now = datetime.now(UTC)
    await backend.enqueue(tenant, version, "content", now)

    class InvalidProvider(FixtureEmbeddingProvider):
        async def embed(self, content: str) -> list[float]:
            return [float("nan")] * 1536

    worker = EmbeddingWorker(backend, InvalidProvider())
    assert (await worker.run_once(uuid4(), "other", now=now)).outcome == "no_job"
    for step, outcome in enumerate(["retry_wait"] * 4 + ["dead"]):
        result = await worker.run_once(tenant, "w", now=now + timedelta(seconds=step * 400))
        assert result.outcome == outcome
    assert len(backend.jobs) == 1 and backend.vectors == {}
    await backend.rebuild(tenant, version, "new", now)
    good = EmbeddingWorker(backend, FixtureEmbeddingProvider())
    assert (await good.run_once(tenant, "w", now=now)).outcome == "succeeded"
    assert len(backend.jobs) == 2
    assert len(backend.vectors[tenant, version][1]) == 1536


@pytest.mark.asyncio
async def test_http_provider_protocol_and_timeout_are_under_caller_control() -> None:
    def endpoint(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer test-token"
        assert b'"model":"test-model"' in request.content
        return httpx.Response(200, json={"data": [{"embedding": [0.25]*1536}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(endpoint), timeout=1) as client:
        provider = HTTPEmbeddingProvider(client, endpoint="https://embedding.test/v1",
                                         model="test-model", token="test-token")
        assert await provider.embed("content") == [0.25]*1536
