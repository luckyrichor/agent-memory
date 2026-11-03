"""E3: the three factors and their guards, tested without a database or a budget."""
from datetime import UTC, datetime, timedelta

import pytest

from agent_memory.application.context_scoring import (
    DEFAULT_HALF_LIFE_DAYS,
    MAX_AUTHORITY,
    ContextScoring,
)
from agent_memory.domain.enums import AuthorityLevel, MemoryType

NOW = datetime(2026, 11, 3, tzinfo=UTC)


def test_relevance_is_relative_to_the_best_hit_on_the_page():
    scoring = ContextScoring()
    assert scoring.relevance_factor(2.0, 2.0) == 1.0
    assert scoring.relevance_factor(1.0, 2.0) == 0.5
    # RRF scores have no absolute scale, so a page whose best hit is small still normalizes to 1.
    assert scoring.relevance_factor(0.016, 0.016) == 1.0
    assert scoring.relevance_factor(0.5, 0.0) == 0.0
    assert scoring.relevance_factor(-1.0, 2.0) == 0.0


def test_recency_halves_at_the_half_life():
    scoring = ContextScoring()
    for memory_type, half_life in DEFAULT_HALF_LIFE_DAYS.items():
        factor = scoring.recency_factor(NOW - timedelta(days=half_life), NOW, memory_type)
        assert factor == pytest.approx(0.5, abs=1e-9)
    assert scoring.recency_factor(NOW, NOW, MemoryType.SEMANTIC) == 1.0
    # A future timestamp (clock skew between writer and reader) must not score above 1.
    assert scoring.recency_factor(NOW + timedelta(days=5), NOW, MemoryType.SEMANTIC) == 1.0


def test_authority_is_normalized_over_the_domain_maximum():
    scoring = ContextScoring()
    assert scoring.authority_factor(0) == 0.0
    assert scoring.authority_factor(int(MAX_AUTHORITY)) == 1.0
    assert scoring.authority_factor(int(AuthorityLevel.USER_CONFIRMED)) == pytest.approx(0.8)
    # Out-of-range values are clamped rather than trusted.
    assert scoring.authority_factor(99) == 1.0


def test_total_never_leaves_the_unit_interval():
    scoring = ContextScoring(relevance_weight=5, recency_weight=1, authority_weight=1)
    low = scoring.total(score=0, best=1, created_at=NOW - timedelta(days=9999), now=NOW,
                        memory_type=MemoryType.EPISODIC, authority_level=0)
    high = scoring.total(score=1, best=1, created_at=NOW, now=NOW,
                         memory_type=MemoryType.PROCEDURAL,
                         authority_level=int(MAX_AUTHORITY))
    assert 0.0 <= low < high <= 1.0


def test_weights_decide_who_wins():
    """Relevance-only ignores age; recency-heavy lets a fresh memory beat a more relevant one."""
    relevance_only = ContextScoring(recency_weight=0, authority_weight=0)
    fresh_but_weak = {
        "score": 1.0, "best": 2.0, "created_at": NOW, "now": NOW,
        "memory_type": MemoryType.SEMANTIC, "authority_level": 2,
    }
    stale_but_strong = {
        "score": 2.0, "best": 2.0, "created_at": NOW - timedelta(days=3650), "now": NOW,
        "memory_type": MemoryType.SEMANTIC, "authority_level": 2,
    }
    assert relevance_only.total(**stale_but_strong) > relevance_only.total(**fresh_but_weak)

    recency_only = ContextScoring(relevance_weight=0, recency_weight=1, authority_weight=0)
    assert recency_only.total(**fresh_but_weak) > recency_only.total(**stale_but_strong)


def test_invalid_configuration_is_rejected_at_construction():
    with pytest.raises(ValueError):
        ContextScoring(relevance_weight=-1)
    with pytest.raises(ValueError):
        ContextScoring(relevance_weight=0, recency_weight=0, authority_weight=0)
    with pytest.raises(ValueError):
        ContextScoring(min_relevance=1.5)
    with pytest.raises(ValueError):
        ContextScoring(half_life_days={MemoryType.SEMANTIC: 0})
