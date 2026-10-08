from datetime import UTC, datetime
from uuid import uuid4

import pytest

from agent_memory.domain.enums import MemoryStatus, MemoryType, ScopeKind
from agent_memory.domain.errors import InvalidStatusTransition
from agent_memory.domain.models import Memory, MemoryScope


def memory():
    now = datetime.now(UTC)
    return Memory(
        tenant_id=uuid4(),
        memory_id=uuid4(),
        memory_type=MemoryType.EPISODIC,
        status=MemoryStatus.ACTIVE,
        owner_user_id=uuid4(),
        current_version_id=uuid4(),
        revision=1,
        scope=MemoryScope(ScopeKind.TENANT, None, None),
        created_at=now,
        updated_at=now,
    )


def test_invalidated_cannot_archive_then_restore():
    invalidated = memory().disable(MemoryStatus.INVALIDATED, datetime.now(UTC))
    with pytest.raises(InvalidStatusTransition):
        invalidated.disable(MemoryStatus.ARCHIVED, datetime.now(UTC))


@pytest.mark.parametrize("terminal", [MemoryStatus.INVALIDATED, MemoryStatus.SUPERSEDED])
def test_terminal_knowledge_only_transitions_to_deleted(terminal):
    m = memory().disable(
        terminal, datetime.now(UTC), uuid4() if terminal is MemoryStatus.SUPERSEDED else None
    )
    for target in (
        MemoryStatus.ACTIVE,
        MemoryStatus.ARCHIVED,
        MemoryStatus.INVALIDATED,
        MemoryStatus.SUPERSEDED,
    ):
        with pytest.raises(InvalidStatusTransition):
            m.disable(target, datetime.now(UTC), uuid4())
    assert m.disable(MemoryStatus.DELETED, datetime.now(UTC)).status is MemoryStatus.DELETED


@pytest.mark.parametrize(
    "text", ["重置 password 流程", "secretary 服务", "Bearer认证流程", "secret 管理规范"]
)
def test_normal_terms_are_not_secrets(text):
    from agent_memory.domain.content_policy import validate_content

    validate_content(text)


@pytest.mark.parametrize(
    "text,reason",
    [
        ("password=foo", "CONTENT_SECRET_VALUE"),
        ("订单号1234567890123456", "CONTENT_NUMERIC_IDENTIFIER"),
        ("ghp_abcdefgh1234567890", "CONTENT_TOKEN_OR_CONTACT"),
    ],
)
def test_rejection_reports_redacted_rule_category(text, reason):
    from agent_memory.domain.content_policy import validate_content
    from agent_memory.domain.errors import ContentRejected

    with pytest.raises(ContentRejected, match=reason):
        validate_content(text)
