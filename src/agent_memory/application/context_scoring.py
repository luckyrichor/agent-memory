"""E3: deterministic relevance + recency + authority scoring for context packing.

Three factors, each normalized to 0..1:

* relevance — the fused retrieval score of this hit relative to the best hit on the page,
* recency  — 0.5 ^ (age / half-life), with a half-life per memory type,
* authority — the version's ``authority_level`` over the highest level the domain allows.

The weights and half-lives are **starting points, not tuned values**. Choosing them needs a dev
set with real embeddings and real user judgements, which this environment does not have (no model
keys, synthetic vectors). What is verified here is the mechanism: that the factors are
deterministic, that all three can move an entry, and that the budget contract still holds.

Two deliberate choices:

* A hit with no ``created_at`` scores 0.5 recency — the neutral point, neither a reward for being
  new nor a punishment for being old. Refusing to score it would silently drop rows whose only
  fault is a test fixture that never set a timestamp.
* Relevance is normalized against the page, not against an absolute scale. Reciprocal-rank fusion
  scores have no absolute meaning (they depend on the number of channels that hit), so an absolute
  threshold would be a number that only looks principled.
"""
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime

from agent_memory.domain.enums import AuthorityLevel, MemoryType

SECONDS_PER_DAY = 86_400.0
MAX_AUTHORITY = float(max(AuthorityLevel))

# How fast a memory's relevance decays with age. Episodic memories describe one moment and go
# stale fastest; procedural knowledge ages slowest. Values are half-lives in days.
DEFAULT_HALF_LIFE_DAYS: Mapping[MemoryType, float] = {
    MemoryType.EPISODIC: 14.0,
    MemoryType.SEMANTIC: 180.0,
    MemoryType.PROCEDURAL: 365.0,
}


@dataclass(frozen=True)
class ContextScoring:
    """Weights for the three factors plus the relevance floor. All factors are 0..1."""

    relevance_weight: float = 1.0
    recency_weight: float = 0.3
    authority_weight: float = 0.3
    min_relevance: float = 0.0
    half_life_days: Mapping[MemoryType, float] = field(
        default_factory=lambda: dict(DEFAULT_HALF_LIFE_DAYS)
    )

    def __post_init__(self) -> None:
        weights = (self.relevance_weight, self.recency_weight, self.authority_weight)
        if min(weights) < 0:
            raise ValueError("weights must not be negative")
        if sum(weights) <= 0:
            raise ValueError("at least one weight must be positive")
        if not 0 <= self.min_relevance <= 1:
            raise ValueError("min_relevance must be 0..1")
        if any(value <= 0 for value in self.half_life_days.values()):
            raise ValueError("half-lives must be positive")

    @property
    def weight_total(self) -> float:
        return self.relevance_weight + self.recency_weight + self.authority_weight

    def relevance_factor(self, score: float, best: float) -> float:
        if best <= 0:
            return 0.0
        return min(1.0, max(0.0, score / best))

    def recency_factor(
        self, created_at: datetime | None, now: datetime, memory_type: MemoryType
    ) -> float:
        if created_at is None:
            return 0.5
        age_days = (now - created_at).total_seconds() / SECONDS_PER_DAY
        if age_days <= 0:
            return 1.0
        half_life = self.half_life_days.get(memory_type)
        if not half_life:
            return 0.5
        return float(0.5 ** (age_days / half_life))

    def authority_factor(self, authority_level: int) -> float:
        return min(1.0, max(0.0, authority_level / MAX_AUTHORITY))

    def total(
        self,
        *,
        score: float,
        best: float,
        created_at: datetime | None,
        now: datetime,
        memory_type: MemoryType,
        authority_level: int,
    ) -> float:
        weighted = (
            self.relevance_weight * self.relevance_factor(score, best)
            + self.recency_weight * self.recency_factor(created_at, now, memory_type)
            + self.authority_weight * self.authority_factor(authority_level)
        )
        return weighted / self.weight_total


def utc_now() -> datetime:
    return datetime.now(UTC)
