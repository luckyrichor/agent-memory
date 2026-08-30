from typing import Protocol

from agent_memory.domain.enums import (
    AuthorityLevel,
    MemoryType,
    VerificationStatus,
)
from agent_memory.domain.events import Event, EventType, MemoryCandidate


class MemoryExtractor(Protocol):
    @property
    def version(self) -> str: ...

    async def extract(self, event: Event) -> tuple[MemoryCandidate, ...]: ...


class CodingFailureRuleExtractor:
    @property
    def version(self) -> str:
        return "coding-failure-rule-v1"

    async def extract(self, event: Event) -> tuple[MemoryCandidate, ...]:
        payload = event.draft.payload
        tool_name = payload.get("tool_name")
        exit_code = payload.get("exit_code")
        summary = payload.get("summary")
        if event.draft.event_type is not EventType.TOOL_RESULT:
            return ()
        if tool_name not in {"build", "test"}:
            return ()
        if not isinstance(exit_code, int) or isinstance(exit_code, bool) or exit_code == 0:
            return ()
        if not isinstance(summary, str) or not summary.strip():
            return ()
        return (
            MemoryCandidate(
                content=summary.strip(),
                memory_type=MemoryType.EPISODIC,
                scope=event.draft.scope,
                confidence=1.0,
                utility=0.5,
                authority_level=AuthorityLevel.TOOL_VERIFIED,
                verification_status=VerificationStatus.VERIFIED,
            ),
        )
