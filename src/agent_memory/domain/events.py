import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from types import MappingProxyType
from uuid import UUID

from agent_memory.domain.enums import (
    AuthorityLevel,
    MemoryType,
    VerificationStatus,
)
from agent_memory.domain.errors import InvalidEvent
from agent_memory.domain.models import MemoryScope

MAX_PAYLOAD_BYTES = 65_536
MAX_PAYLOAD_DEPTH = 4


class EventType(str, Enum):
    TOOL_RESULT = "tool.result"
    TASK_COMPLETED = "task.completed"
    USER_CONFIRMED = "user.confirmed"


def _container_depth(value: object) -> int:
    if isinstance(value, Mapping):
        return 1 + max((_container_depth(item) for item in value.values()), default=0)
    if isinstance(value, (list, tuple)):
        return 1 + max((_container_depth(item) for item in value), default=0)
    return 0


@dataclass(frozen=True, slots=True)
class EventDraft:
    idempotency_key: str
    session_id: str
    sequence_number: int
    event_type: EventType
    agent_id: str
    occurred_at: datetime
    scope: MemoryScope
    payload: Mapping[str, object]

    def __post_init__(self) -> None:
        for field_name in ("idempotency_key", "session_id", "agent_id"):
            if not str(getattr(self, field_name)).strip():
                raise InvalidEvent(f"{field_name} must not be blank")
        if self.sequence_number < 1:
            raise InvalidEvent("sequence_number must be positive")
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise InvalidEvent("occurred_at must include a timezone")
        if _container_depth(self.payload) > MAX_PAYLOAD_DEPTH:
            raise InvalidEvent("payload depth exceeds four containers")
        try:
            encoded = json.dumps(
                self.payload,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode()
        except (TypeError, ValueError) as error:
            raise InvalidEvent("payload must contain JSON values") from error
        if len(encoded) > MAX_PAYLOAD_BYTES:
            raise InvalidEvent("payload exceeds 65,536 UTF-8 bytes")
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))

    def request_hash(self) -> str:
        body = {
            "agent_id": self.agent_id,
            "event_type": self.event_type.value,
            "idempotency_key": self.idempotency_key,
            "occurred_at": self.occurred_at.astimezone(UTC).isoformat(),
            "payload": dict(self.payload),
            "scope": {
                "kind": self.scope.kind.value,
                "subject_user_id": (
                    str(self.scope.subject_user_id) if self.scope.subject_user_id else None
                ),
                "workspace_id": self.scope.workspace_id,
            },
            "sequence_number": self.sequence_number,
            "session_id": self.session_id,
        }
        encoded = json.dumps(
            body,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class Event:
    tenant_id: UUID
    event_id: UUID
    draft: EventDraft
    actor_user_id: UUID
    received_at: datetime


@dataclass(frozen=True, slots=True)
class MemoryCandidate:
    content: str
    memory_type: MemoryType
    scope: MemoryScope
    confidence: float
    utility: float
    authority_level: AuthorityLevel
    verification_status: VerificationStatus

    def __post_init__(self) -> None:
        if not self.content.strip():
            raise InvalidEvent("candidate content must not be blank")
        if not 0 <= self.confidence <= 1:
            raise InvalidEvent("candidate confidence must be between zero and one")
        if not 0 <= self.utility <= 1:
            raise InvalidEvent("candidate utility must be between zero and one")
