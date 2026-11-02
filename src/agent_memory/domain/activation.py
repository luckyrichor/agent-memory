"""Policy deciding the first status of an extracted candidate memory.

Extraction output is an *agent inference*, not a user statement. Before this policy existed,
candidates had no path to ``active`` at all, so extracted memories could never be retrieved.

* ``manual``: every candidate waits as ``candidate`` for an explicit review decision.
* ``auto``: low-risk candidates become ``active`` immediately; high-risk ones go to
  ``needs_review``. High risk reuses the explicit-write rule: a tenant-wide procedural memory
  changes behaviour for everyone, so a human must accept it.

The policy never changes content or scope; it only picks the starting status.
"""
from typing import Literal

from agent_memory.domain.enums import MemoryStatus, MemoryType, ScopeKind
from agent_memory.domain.events import MemoryCandidate

ActivationMode = Literal["auto", "manual"]


def is_high_risk(candidate: MemoryCandidate) -> bool:
    return (
        candidate.memory_type is MemoryType.PROCEDURAL
        and candidate.scope.kind is ScopeKind.TENANT
    )


def initial_status(candidate: MemoryCandidate, mode: ActivationMode) -> MemoryStatus:
    if mode == "manual":
        return MemoryStatus.CANDIDATE
    return MemoryStatus.NEEDS_REVIEW if is_high_risk(candidate) else MemoryStatus.ACTIVE
