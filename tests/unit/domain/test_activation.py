from datetime import UTC, datetime
from uuid import uuid4

import pytest

from agent_memory.domain.activation import initial_status, is_high_risk
from agent_memory.domain.enums import (
    AuthorityLevel,
    MemoryStatus,
    MemoryType,
    ScopeKind,
    VerificationStatus,
)
from agent_memory.domain.errors import InvalidStatusTransition
from agent_memory.domain.events import MemoryCandidate
from agent_memory.domain.models import Memory, MemoryScope

NOW = datetime(2026, 11, 2, tzinfo=UTC)


def candidate(memory_type: MemoryType, kind: ScopeKind) -> MemoryCandidate:
    workspace = "project-a" if kind is ScopeKind.WORKSPACE else None
    return MemoryCandidate(
        content="x", memory_type=memory_type, scope=MemoryScope(kind, workspace, None),
        confidence=0.5, utility=0.5, authority_level=AuthorityLevel.AGENT_INFERENCE,
        verification_status=VerificationStatus.UNVERIFIED,
    )


def test_manual_mode_always_waits_as_candidate() -> None:
    for memory_type in MemoryType:
        assert initial_status(candidate(memory_type, ScopeKind.WORKSPACE), "manual") is (
            MemoryStatus.CANDIDATE
        )


def test_auto_mode_activates_low_risk_and_holds_tenant_procedures_for_review() -> None:
    assert initial_status(candidate(MemoryType.EPISODIC, ScopeKind.WORKSPACE), "auto") is (
        MemoryStatus.ACTIVE
    )
    assert initial_status(candidate(MemoryType.PROCEDURAL, ScopeKind.WORKSPACE), "auto") is (
        MemoryStatus.ACTIVE
    )
    risky = candidate(MemoryType.PROCEDURAL, ScopeKind.TENANT)
    assert is_high_risk(risky)
    assert initial_status(risky, "auto") is MemoryStatus.NEEDS_REVIEW


def make(status: MemoryStatus) -> Memory:
    memory, _ = Memory.create(
        tenant_id=uuid4(), memory_id=uuid4(), version_id=uuid4(),
        memory_type=MemoryType.SEMANTIC, scope=MemoryScope(ScopeKind.TENANT, None, None),
        owner_user_id=uuid4(), content="x", now=NOW, status=status,
    )
    return memory


@pytest.mark.parametrize("start", [MemoryStatus.CANDIDATE, MemoryStatus.NEEDS_REVIEW])
def test_review_accepts_or_rejects_unreviewed_memory(start: MemoryStatus) -> None:
    accepted = make(start).review(MemoryStatus.ACTIVE, NOW)
    assert accepted.status is MemoryStatus.ACTIVE and accepted.revision == 2
    assert accepted.disabled_at is None
    rejected = make(start).review(MemoryStatus.REJECTED, NOW)
    assert rejected.status is MemoryStatus.REJECTED and rejected.disabled_at == NOW


@pytest.mark.parametrize(
    "start",
    [MemoryStatus.ACTIVE, MemoryStatus.ARCHIVED, MemoryStatus.REJECTED, MemoryStatus.DELETED],
)
def test_review_is_refused_for_already_decided_memory(start: MemoryStatus) -> None:
    with pytest.raises(InvalidStatusTransition):
        make(start).review(MemoryStatus.ACTIVE, NOW)


def test_review_cannot_pick_arbitrary_target_status() -> None:
    with pytest.raises(InvalidStatusTransition):
        make(MemoryStatus.CANDIDATE).review(MemoryStatus.ARCHIVED, NOW)
