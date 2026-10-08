"""Process-local, tenant/model-bound LRU; no plaintext query retained."""

import asyncio
import hashlib
import time
from collections import OrderedDict
from uuid import UUID

import httpx

from agent_memory.application.retrieval import RetrievalQuery
from agent_memory.config import Settings
from agent_memory.infrastructure.embedding import HTTPEmbeddingProvider


class QueryVectors:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._slots = asyncio.Semaphore(settings.query_embedding_concurrency)
        self._cache: OrderedDict[tuple[UUID, str], tuple[float, tuple[float, ...]]] = OrderedDict()
        self._client: httpx.AsyncClient | None = None

    async def embed(self, tenant: UUID, text: str) -> tuple[list[float], str]:
        s = self.settings
        key = (
            tenant,
            hashlib.sha256(
                (s.embedding_endpoint + "\0" + s.embedding_model + "\0" + text).encode()
            ).hexdigest(),
        )
        hit = self._cache.get(key)
        if hit is not None and hit[0] > time.monotonic():
            self._cache.move_to_end(key)
            return list(hit[1]), "cache"
        self._cache.pop(key, None)
        async with asyncio.timeout(s.query_embedding_timeout_seconds):
            async with self._slots:
                hit = self._cache.get(key)
                if hit is not None and hit[0] > time.monotonic():
                    self._cache.move_to_end(key)
                    return list(hit[1]), "cache"
                self._cache.pop(key, None)
                if self._client is None:
                    self._client = httpx.AsyncClient(
                        timeout=s.query_embedding_timeout_seconds,
                        trust_env=s.embedding_trust_env,
                        limits=httpx.Limits(
                            max_connections=s.query_embedding_concurrency,
                            max_keepalive_connections=s.query_embedding_concurrency,
                        ),
                    )
                provider = HTTPEmbeddingProvider(
                    self._client,
                    endpoint=s.embedding_endpoint,
                    model=s.embedding_model,
                    token=s.embedding_token.get_secret_value(),
                    protocol=s.embedding_protocol,
                )
                vector = await provider.embed(text)
                RetrievalQuery(text, tuple(vector), s.embedding_model)
                self._cache[key] = (
                    time.monotonic() + s.query_embedding_cache_seconds,
                    tuple(vector),
                )
                self._cache.move_to_end(key)
                while len(self._cache) > s.query_embedding_cache_size:
                    self._cache.popitem(last=False)
                return vector, "provider"

    async def aclose(self) -> None:
        self._cache.clear()
        if self._client is not None:
            await self._client.aclose()
