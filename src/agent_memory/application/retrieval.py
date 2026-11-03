"""Authorized candidate retrieval and deterministic reciprocal-rank fusion."""
import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
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
    """Channel output carries ids and a score only; body text is fetched for the page alone."""

    memory_id: UUID
    version_id: UUID
    channel: str
    raw_score: float


# At most this many evidence references travel with one hit; the rest is only counted.
EVIDENCE_PER_HIT = 5


@dataclass(frozen=True)
class EvidenceRef:
    """Pointer to the source event of a memory version. Carries NO event payload text: only the
    event id and the caller's own coordinates (session, sequence, type, time) so the citation can
    be located in the caller's transcript. There is no event read API to resolve the id."""

    event_id: UUID
    role: str
    event_type: str
    occurred_at: datetime
    session_id: str
    sequence_number: int


@dataclass(frozen=True)
class VersionEvidence:
    refs: tuple[EvidenceRef, ...]
    total: int  # all evidence rows of the version, refs may be a capped subset


@dataclass(frozen=True)
class RetrievalHit:
    memory_id: UUID
    version_id: UUID
    content: str
    score: float
    ranks: dict[str, int]
    raw_scores: dict[str, float]
    evidence: tuple[EvidenceRef, ...] = ()
    evidence_total: int = 0


class CandidateProvider(Protocol):
    async def candidates(self, query: RetrievalQuery,
                         principal: RequestPrincipal) -> list[Candidate]: ...

    async def contents(self, version_ids: Sequence[UUID],
                       principal: RequestPrincipal) -> dict[UUID, str]:
        """Body text of already-authorized versions; unknown or foreign ids are simply absent."""
        ...

    async def evidence(self, version_ids: Sequence[UUID], principal: RequestPrincipal,
                       per_version: int) -> dict[UUID, VersionEvidence]:
        """Source-event references of already-authorized versions (E1); absent = none recorded.
        Origin and contradicting evidence rank before plain support when the list is capped."""
        ...


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
            fused = [(memory_id, entries[0][0].version_id,
                      sum((0.25 if candidate.channel == "structured" else 1) / (60 + rank)
                          for candidate, rank in entries),
                      {candidate.channel: rank for candidate, rank in entries},
                      {candidate.channel: candidate.raw_score for candidate, _ in entries})
                     for memory_id, entries in grouped.items()]
            fused.sort(key=lambda item: (-item[2], str(item[0])))
            end = query.offset + query.limit
            page = fused[query.offset:end]
            # Second stage: only the current page (<= 100 rows) needs its body text.
            page_versions = [item[1] for item in page]
            contents = (await self.provider.contents(page_versions, principal) if page else {})
            evidence = (await self.provider.evidence(page_versions, principal, EVIDENCE_PER_HIT)
                        if page else {})
            hits = [RetrievalHit(memory_id, version_id, contents[version_id], score,
                                 hit_ranks, raw_scores,
                                 evidence[version_id].refs if version_id in evidence else (),
                                 evidence[version_id].total if version_id in evidence else 0)
                    for memory_id, version_id, score, hit_ranks, raw_scores in page
                    if version_id in contents]
            return RetrievalPage(tuple(hits),
                                 end if end < len(fused) else None,
                                 {channel: ranks.get(channel, 0)
                                  for channel in ("lexical", "vector", "structured")})
