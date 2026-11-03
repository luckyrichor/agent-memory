"""C5 / O4: identical content in the same tenant and model is embedded once."""
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from agent_memory.application.embedding import EmbeddingWorker
from agent_memory.infrastructure.embedding import FixtureEmbeddingProvider
from agent_memory.infrastructure.in_memory_embedding import InMemoryEmbeddingBackend

NOW = datetime(2026, 11, 3, tzinfo=UTC)


class CountingProvider(FixtureEmbeddingProvider):
    def __init__(self, model: str = "fixture-sha256-1024-v1") -> None:
        super().__init__()
        self.model = model
        self.calls = 0

    async def embed(self, content: str) -> list[float]:
        self.calls += 1
        return await super().embed(content)


async def run(backend: InMemoryEmbeddingBackend, provider: CountingProvider, tenant) -> str:
    result = await EmbeddingWorker(backend, provider).run_once(tenant, "w", now=NOW)
    assert result.outcome == "succeeded"
    return result.reason_code


@pytest.mark.asyncio
async def test_identical_content_in_same_tenant_is_embedded_once() -> None:
    backend, provider, tenant = InMemoryEmbeddingBackend(), CountingProvider(), uuid4()
    first, second = uuid4(), uuid4()
    await backend.enqueue(tenant, first, "我喜欢深色主题", NOW)
    await backend.enqueue(tenant, second, "我喜欢深色主题", NOW)
    assert await run(backend, provider, tenant) == "EMBEDDING_SUCCEEDED"
    assert await run(backend, provider, tenant) == "EMBEDDING_REUSED"
    assert provider.calls == 1
    assert backend.vectors[tenant, first][1] == backend.vectors[tenant, second][1]


@pytest.mark.asyncio
async def test_near_duplicates_are_not_reused() -> None:
    """Exact match only: '深色主题' vs '深色的主题' must each get their own vector."""
    backend, provider, tenant = InMemoryEmbeddingBackend(), CountingProvider(), uuid4()
    await backend.enqueue(tenant, uuid4(), "我喜欢深色主题", NOW)
    await backend.enqueue(tenant, uuid4(), "我喜欢深色的主题", NOW)
    await run(backend, provider, tenant)
    await run(backend, provider, tenant)
    assert provider.calls == 2


@pytest.mark.asyncio
async def test_never_reused_across_tenants() -> None:
    backend, provider = InMemoryEmbeddingBackend(), CountingProvider()
    a, b = uuid4(), uuid4()
    await backend.enqueue(a, uuid4(), "shared sentence", NOW)
    await backend.enqueue(b, uuid4(), "shared sentence", NOW)
    await run(backend, provider, a)
    assert await run(backend, provider, b) == "EMBEDDING_SUCCEEDED"
    assert provider.calls == 2


@pytest.mark.asyncio
async def test_never_reused_across_models() -> None:
    backend, tenant = InMemoryEmbeddingBackend(), uuid4()
    await backend.enqueue(tenant, uuid4(), "same text", NOW)
    await backend.enqueue(tenant, uuid4(), "same text", NOW)
    old, new = CountingProvider("model-a"), CountingProvider("model-b")
    await run(backend, old, tenant)
    assert await run(backend, new, tenant) == "EMBEDDING_SUCCEEDED"
    assert (old.calls, new.calls) == (1, 1)


@pytest.mark.asyncio
async def test_rebuild_always_recomputes() -> None:
    backend, provider, tenant = InMemoryEmbeddingBackend(), CountingProvider(), uuid4()
    first, second = uuid4(), uuid4()
    await backend.enqueue(tenant, first, "same text", NOW)
    await backend.enqueue(tenant, second, "same text", NOW)
    await run(backend, provider, tenant)
    await run(backend, provider, tenant)  # reused
    await backend.rebuild(tenant, second, "operator-rebuild", NOW)
    assert await run(backend, provider, tenant) == "EMBEDDING_SUCCEEDED"
    assert provider.calls == 2
