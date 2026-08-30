from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import UUID

import pytest

from agent_memory.application.commands import (
    CorrectMemoryCommand,
    DisableMemoryCommand,
    RememberMemoryCommand,
)
from agent_memory.application.explicit_memory import ExplicitMemoryService
from agent_memory.domain.enums import MemoryStatus, MemoryType, ScopeKind
from agent_memory.domain.errors import (
    IdempotencyConflict,
    MemoryNotFound,
    MemoryScopeForbidden,
)
from agent_memory.domain.models import MemoryScope
from agent_memory.domain.principal import RequestPrincipal
from agent_memory.infrastructure.in_memory import (
    InMemoryAuditSink,
    InMemoryIdempotencyRepository,
    InMemoryMemoryRepository,
)

TENANT_ID = UUID("00000000-0000-0000-0000-00000000000a")
USER_ID = UUID("00000000-0000-0000-0000-00000000000b")
MEMORY_ID = UUID("00000000-0000-0000-0000-00000000000c")
VERSION_1_ID = UUID("00000000-0000-0000-0000-00000000000d")
VERSION_2_ID = UUID("00000000-0000-0000-0000-00000000000e")
NOW = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)


def principal(*, admin: bool = False) -> RequestPrincipal:
    permissions = {"memory:read", "memory:write", "memory:delete"}
    if admin:
        permissions.add("memory:admin")
    return RequestPrincipal(
        tenant_id=TENANT_ID,
        user_id=USER_ID,
        roles=frozenset({"developer"}),
        permissions=frozenset(permissions),
        allowed_workspace_ids=frozenset({"project-a"}),
    )


def make_service() -> tuple[
    ExplicitMemoryService,
    InMemoryMemoryRepository,
    InMemoryAuditSink,
]:
    ids: Iterator[UUID] = iter((MEMORY_ID, VERSION_1_ID, VERSION_2_ID))
    repository = InMemoryMemoryRepository()
    audit = InMemoryAuditSink()
    service = ExplicitMemoryService(
        memory_repository=repository,
        idempotency_repository=InMemoryIdempotencyRepository(),
        audit_sink=audit,
        new_id=lambda: next(ids),
        now=lambda: NOW,
    )
    return service, repository, audit


def workspace_command(
    *,
    content: str = "项目 A 只能使用 Java 17",
    idempotency_key: str = "remember-1",
) -> RememberMemoryCommand:
    return RememberMemoryCommand(
        content=content,
        memory_type=MemoryType.SEMANTIC,
        scope=MemoryScope(ScopeKind.WORKSPACE, "project-a", None),
        idempotency_key=idempotency_key,
    )


@pytest.mark.asyncio
async def test_workspace_memory_requires_workspace_access() -> None:
    service, _, audit = make_service()
    forbidden_principal = RequestPrincipal(
        tenant_id=TENANT_ID,
        user_id=USER_ID,
        roles=frozenset({"developer"}),
        permissions=frozenset({"memory:write"}),
        allowed_workspace_ids=frozenset({"project-b"}),
    )

    with pytest.raises(MemoryScopeForbidden):
        await service.remember(workspace_command(), forbidden_principal)

    assert audit.entries[-1].decision == "deny"
    assert audit.entries[-1].reason_code == "MEMORY_SCOPE_FORBIDDEN"


@pytest.mark.asyncio
async def test_identical_idempotent_replay_returns_same_memory() -> None:
    service, repository, audit = make_service()

    first = await service.remember(workspace_command(), principal())
    replay = await service.remember(workspace_command(), principal())

    assert replay == first
    assert repository.count == 1
    assert [entry.decision for entry in audit.entries] == ["allow", "allow"]


@pytest.mark.asyncio
async def test_idempotency_key_reuse_with_different_content_is_rejected() -> None:
    service, _, audit = make_service()
    await service.remember(workspace_command(), principal())

    with pytest.raises(IdempotencyConflict):
        await service.remember(
            workspace_command(content="项目 A 使用 Java 21"),
            principal(),
        )

    assert audit.entries[-1].decision == "deny"
    assert audit.entries[-1].reason_code == "IDEMPOTENCY_CONFLICT"


@pytest.mark.asyncio
async def test_non_admin_tenant_procedural_memory_needs_review() -> None:
    service, _, _ = make_service()
    command = RememberMemoryCommand(
        content="生产部署不需要审批",
        memory_type=MemoryType.PROCEDURAL,
        scope=MemoryScope(ScopeKind.TENANT, None, None),
        idempotency_key="tenant-procedure-1",
    )

    result = await service.remember(command, principal())

    assert result.status is MemoryStatus.NEEDS_REVIEW


@pytest.mark.asyncio
async def test_correction_creates_new_version_without_overwriting_original() -> None:
    service, repository, _ = make_service()
    created = await service.remember(workspace_command(), principal())

    corrected = await service.correct(
        CorrectMemoryCommand(
            memory_id=created.memory_id,
            expected_revision=1,
            content="项目 A 已升级为 Java 21",
            reason="user_correction",
        ),
        principal(),
    )

    record = await repository.get(TENANT_ID, created.memory_id)
    assert record is not None
    assert corrected.revision == 2
    assert [version.content for version in record.versions] == [
        "项目 A 只能使用 Java 17",
        "项目 A 已升级为 Java 21",
    ]


@pytest.mark.asyncio
async def test_deleted_memory_is_immediately_excluded_from_active_reads() -> None:
    service, repository, _ = make_service()
    created = await service.remember(workspace_command(), principal())

    await service.disable(
        DisableMemoryCommand(
            memory_id=created.memory_id,
            expected_revision=1,
            status=MemoryStatus.DELETED,
        ),
        principal(),
    )

    deleted_record = await repository.get(TENANT_ID, created.memory_id)
    assert deleted_record is not None
    assert deleted_record.memory.status is MemoryStatus.DELETED
    assert deleted_record.memory.revision == 2

    with pytest.raises(MemoryNotFound):
        await service.get_active(created.memory_id, principal())
