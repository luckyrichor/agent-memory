"""Authorized candidate retrieval and deterministic reciprocal-rank fusion."""
import math
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from agent_memory.domain.enums import MemoryType
from agent_memory.domain.errors import MemoryScopeForbidden
from agent_memory.domain.principal import RequestPrincipal
from agent_memory.observability import span


@dataclass(frozen=True)
class RetrievalQuery:
    text: str
    vector: tuple[float, ...] | None = None
    model: str | None = None
    memory_type: MemoryType | None = None
    workspace_id: str | None = None
    limit: int = 20
    offset: int = 0

    def __post_init__(self) -> None:
        if not 1 <= self.limit <= 100 or not 0 <= self.offset <= 2900:
            raise ValueError("invalid pagination")
        if self.vector is not None and (len(self.vector) != 1024 or
                not all(math.isfinite(x) for x in self.vector) or
                not any(self.vector) or not self.model):
            raise ValueError("vector requires a model and 1024 finite nonzero dimensions")


@dataclass(frozen=True)
class Candidate:
    memory_id: UUID
    version_id: UUID
    content: str
    channel: str
    raw_score: float


@dataclass(frozen=True)
class RetrievalHit:
    memory_id: UUID
    version_id: UUID
    content: str
    score: float
    ranks: dict[str, int]
    raw_scores: dict[str, float]


class CandidateProvider(Protocol):
    async def candidates(self, query: RetrievalQuery,
                         principal: RequestPrincipal) -> list[Candidate]: ...


@dataclass(frozen=True)
class RetrievalPage:
    items: tuple[RetrievalHit, ...]
    next_offset: int | None
    channel_counts: dict[str, int]


class MemoryRetriever:
    def __init__(self, provider: CandidateProvider) -> None:
        self.provider = provider

    async def search(self, query: RetrievalQuery, principal: RequestPrincipal) -> RetrievalPage:
        if "memory:read" not in principal.permissions:
            raise MemoryScopeForbidden("memory:read")
        if query.workspace_id is not None and not principal.can_access_workspace(query.workspace_id):
            raise MemoryScopeForbidden(query.workspace_id)
        with span("memory.search", action="memory.search", tenant_id=principal.tenant_id):
            candidates = await self.provider.candidates(query, principal)
            ranks: dict[str, int] = {}
            grouped: dict[UUID, list[tuple[Candidate, int]]] = {}
            for candidate in candidates:
                ranks[candidate.channel] = ranks.get(candidate.channel, 0) + 1
                grouped.setdefault(candidate.memory_id, []).append(
                    (candidate, ranks[candidate.channel]))
            hits = [RetrievalHit(memory_id, entries[0][0].version_id, entries[0][0].content,
                    sum((0.25 if candidate.channel == "structured" else 1) / (60 + rank)
                        for candidate, rank in entries),
                    {candidate.channel: rank for candidate, rank in entries},
                    {candidate.channel: candidate.raw_score for candidate, _ in entries})
                    for memory_id, entries in grouped.items()]
            hits.sort(key=lambda hit: (-hit.score, str(hit.memory_id)))
            end = query.offset + query.limit
            return RetrievalPage(tuple(hits[query.offset:end]),
                                 end if end < len(hits) else None,
                                 {channel: ranks.get(channel, 0)
                                  for channel in ("lexical", "vector", "structured")})
