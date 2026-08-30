from datetime import UTC, datetime
from uuid import UUID

import pytest

from agent_memory.domain.enums import (
    AuthorityLevel,
    MemoryStatus,
    MemoryType,
    ScopeKind,
    VerificationStatus,
)
from agent_memory.domain.errors import InvalidScope, InvalidStatusTransition, RevisionConflict
from agent_memory.domain.models import Memory, MemoryScope
from agent_memory.domain.principal import RequestPrincipal

TENANT_ID = UUID("00000000-0000-0000-0000-00000000000a")
USER_ID = UUID("00000000-0000-0000-0000-00000000000b")
MEMORY_ID = UUID("00000000-0000-0000-0000-00000000000c")
VERSION_1_ID = UUID("00000000-0000-0000-0000-00000000000d")
VERSION_2_ID = UUID("00000000-0000-0000-0000-00000000000e")
NOW = datetime(2026, 8, 30, 10, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("kind", "workspace_id", "subject_user_id"),
    [
        (ScopeKind.TENANT, None, None),
        (ScopeKind.WORKSPACE, "project-a", None),
        (ScopeKind.USER_GLOBAL, None, USER_ID),
        (ScopeKind.USER_WORKSPACE, "project-a", USER_ID),
    ],
)
def test_valid_scope_combinations_are_accepted(
    kind: ScopeKind,
    workspace_id: str | None,
    subject_user_id: UUID | None,
) -> None:
    scope = MemoryScope(kind, workspace_id, subject_user_id)

    assert scope.kind is kind


@pytest.mark.parametrize(
    ("kind", "workspace_id", "subject_user_id"),
    [
        (ScopeKind.TENANT, "project-a", None),
        (ScopeKind.WORKSPACE, None, None),
        (ScopeKind.USER_GLOBAL, None, None),
        (ScopeKind.USER_WORKSPACE, "project-a", None),
    ],
)
def test_invalid_scope_combinations_are_rejected(
    kind: ScopeKind,
    workspace_id: str | None,
    subject_user_id: UUID | None,
) -> None:
    with pytest.raises(InvalidScope):
        MemoryScope(kind, workspace_id, subject_user_id)


def test_adding_version_preserves_old_aggregate_and_increments_revision() -> None:
    original, version_1 = Memory.create(
        tenant_id=TENANT_ID,
        memory_id=MEMORY_ID,
        version_id=VERSION_1_ID,
        memory_type=MemoryType.EPISODIC,
        scope=MemoryScope(ScopeKind.WORKSPACE, "project-a", None),
        owner_user_id=USER_ID,
        content="可能由依赖架构不匹配导致",
        now=NOW,
    )

    updated, version_2 = original.add_version(
        version_id=VERSION_2_ID,
        content="确认由 x86_64 依赖导致，替换后测试通过",
        expected_revision=1,
        now=NOW,
    )

    assert original.revision == 1
    assert original.current_version_id == VERSION_1_ID
    assert version_1.content == "可能由依赖架构不匹配导致"
    assert updated.revision == 2
    assert updated.current_version_id == VERSION_2_ID
    assert version_2.version_number == 2
    assert version_2.content == "确认由 x86_64 依赖导致，替换后测试通过"


def test_stale_revision_cannot_append_version() -> None:
    memory, _ = Memory.create(
        tenant_id=TENANT_ID,
        memory_id=MEMORY_ID,
        version_id=VERSION_1_ID,
        memory_type=MemoryType.SEMANTIC,
        scope=MemoryScope(ScopeKind.WORKSPACE, "project-a", None),
        owner_user_id=USER_ID,
        content="Java 11",
        now=NOW,
    )

    with pytest.raises(RevisionConflict, match="expected revision 0, current revision 1"):
        memory.add_version(
            version_id=VERSION_2_ID,
            content="Java 17",
            expected_revision=0,
            now=NOW,
        )


def test_deleted_memory_cannot_transition_again() -> None:
    memory, _ = Memory.create(
        tenant_id=TENANT_ID,
        memory_id=MEMORY_ID,
        version_id=VERSION_1_ID,
        memory_type=MemoryType.EPISODIC,
        scope=MemoryScope(ScopeKind.WORKSPACE, "project-a", None),
        owner_user_id=USER_ID,
        content="resolved failure",
        now=NOW,
    )
    deleted = memory.disable(MemoryStatus.DELETED, NOW)

    with pytest.raises(InvalidStatusTransition, match="deleted memory is terminal"):
        deleted.disable(MemoryStatus.ARCHIVED, NOW)


def test_principal_workspace_access_is_explicit() -> None:
    principal = RequestPrincipal(
        tenant_id=TENANT_ID,
        user_id=USER_ID,
        roles=frozenset({"developer"}),
        permissions=frozenset({"memory:read"}),
        allowed_workspace_ids=frozenset({"project-a"}),
    )

    assert principal.can_access_workspace("project-a") is True
    assert principal.can_access_workspace("project-b") is False
    assert principal.can_access_workspace(None) is False


def test_candidate_memory_preserves_extractor_trust_dimensions() -> None:
    memory, version = Memory.create(
        tenant_id=TENANT_ID,
        memory_id=MEMORY_ID,
        version_id=VERSION_1_ID,
        memory_type=MemoryType.EPISODIC,
        scope=MemoryScope(ScopeKind.WORKSPACE, "project-a", None),
        owner_user_id=USER_ID,
        content="build failed on arm64",
        now=NOW,
        status=MemoryStatus.CANDIDATE,
        confidence=1.0,
        utility=0.5,
        authority_level=AuthorityLevel.TOOL_VERIFIED,
        verification_status=VerificationStatus.VERIFIED,
    )

    assert memory.status is MemoryStatus.CANDIDATE
    assert version.confidence == 1.0
    assert version.utility == 0.5
    assert version.authority_level is AuthorityLevel.TOOL_VERIFIED
    assert version.verification_status is VerificationStatus.VERIFIED
