import asyncio
import sys
from collections.abc import Awaitable, Callable, Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TextIO
from uuid import UUID, uuid4

from agent_memory.application.commands import (
    CorrectMemoryCommand,
    DisableMemoryCommand,
    RememberMemoryCommand,
)
from agent_memory.application.event_commands import IngestEventBatchCommand
from agent_memory.application.event_ingestion import EventIngestionService
from agent_memory.application.explicit_memory import ExplicitMemoryService
from agent_memory.application.extraction import CodingFailureRuleExtractor
from agent_memory.application.outbox_dispatcher import OutboxDispatcher
from agent_memory.domain.enums import MemoryStatus, MemoryType, ScopeKind
from agent_memory.domain.errors import (
    InvalidScope,
    MemoryError,
    MemoryNotFound,
    RevisionConflict,
)
from agent_memory.domain.events import Event, EventDraft, EventType
from agent_memory.domain.models import Memory, MemoryScope
from agent_memory.domain.principal import RequestPrincipal
from agent_memory.evals.schema import FoundationActual, FoundationCase, FoundationScore
from agent_memory.infrastructure.in_memory import (
    InMemoryAuditSink,
    InMemoryIdempotencyRepository,
    InMemoryMemoryRepository,
)
from agent_memory.infrastructure.in_memory_events import InMemoryEventIngestionRepository

TENANT_A = UUID("00000000-0000-0000-0000-00000000000a")
TENANT_B = UUID("00000000-0000-0000-0000-00000000000b")
USER_A = UUID("00000000-0000-0000-0000-00000000000c")
USER_B = UUID("00000000-0000-0000-0000-00000000000d")
WORKSPACE_ID = "project-a"


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    case_id: str
    passed: bool
    reason_code: str
    tenant_leak: bool = False
    deleted_memory_hit: bool = False
    diagnostic: str | None = None


def evaluate_foundation_case(
    case: FoundationCase,
    actual: FoundationActual,
) -> FoundationScore:
    if actual.tenant_id != case.tenant_id:
        raise ValueError("tenant mismatch")

    reasons: list[str] = []
    if actual.memory_type != case.expected_memory_type:
        reasons.append("memory_type_mismatch")
    if actual.scope_kind != case.expected_scope_kind:
        reasons.append("scope_kind_mismatch")
    if actual.content != case.expected_content:
        reasons.append("content_mismatch")
    if actual.status != "active":
        reasons.append("memory_not_active")

    return FoundationScore(passed=not reasons, reasons=tuple(reasons))


def _principal(tenant_id: UUID, user_id: UUID) -> RequestPrincipal:
    return RequestPrincipal(
        tenant_id=tenant_id,
        user_id=user_id,
        roles=frozenset({"developer"}),
        permissions=frozenset({"memory:read", "memory:write", "memory:delete"}),
        allowed_workspace_ids=frozenset({WORKSPACE_ID}),
    )


def _service() -> tuple[ExplicitMemoryService, InMemoryMemoryRepository]:
    repository = InMemoryMemoryRepository()
    return (
        ExplicitMemoryService(
            memory_repository=repository,
            idempotency_repository=InMemoryIdempotencyRepository(),
            audit_sink=InMemoryAuditSink(),
            new_id=uuid4,
            now=lambda: datetime.now(UTC),
        ),
        repository,
    )


def _workspace_command(key: str = "foundation-workspace") -> RememberMemoryCommand:
    return RememberMemoryCommand(
        content="private build diagnostic",
        memory_type=MemoryType.EPISODIC,
        scope=MemoryScope(ScopeKind.WORKSPACE, WORKSPACE_ID, None),
        idempotency_key=key,
    )


async def _valid_workspace_memory() -> bool:
    service, _ = _service()
    result = await service.remember(_workspace_command(), _principal(TENANT_A, USER_A))
    return result.status is MemoryStatus.ACTIVE


async def _invalid_scope_combination() -> bool:
    try:
        MemoryScope(ScopeKind.WORKSPACE, None, None)
    except InvalidScope:
        return True
    return False


async def _idempotent_replay() -> bool:
    service, repository = _service()
    principal = _principal(TENANT_A, USER_A)
    first = await service.remember(_workspace_command(), principal)
    replay = await service.remember(_workspace_command(), principal)
    return first == replay and repository.count == 1


async def _stale_revision_rejection() -> bool:
    service, _ = _service()
    principal = _principal(TENANT_A, USER_A)
    created = await service.remember(_workspace_command(), principal)
    await service.correct(
        CorrectMemoryCommand(created.memory_id, 1, "corrected diagnostic", "evaluation"),
        principal,
    )
    try:
        await service.correct(
            CorrectMemoryCommand(created.memory_id, 1, "stale diagnostic", "evaluation"),
            principal,
        )
    except RevisionConflict:
        return True
    return False


async def _deleted_memory_exclusion() -> bool:
    service, _ = _service()
    principal = _principal(TENANT_A, USER_A)
    created = await service.remember(_workspace_command(), principal)
    await service.disable(
        DisableMemoryCommand(created.memory_id, 1, MemoryStatus.DELETED),
        principal,
    )
    try:
        await service.get_active(created.memory_id, principal)
    except MemoryNotFound:
        return True
    return False


async def _tenant_known_id_attack() -> bool:
    service, _ = _service()
    created = await service.remember(
        _workspace_command(),
        _principal(TENANT_A, USER_A),
    )
    try:
        await service.get_active(created.memory_id, _principal(TENANT_B, USER_B))
    except MemoryNotFound:
        return True
    return False


async def _tenant_procedure_needs_review() -> bool:
    service, _ = _service()
    result = await service.remember(
        RememberMemoryCommand(
            content="unreviewed tenant procedure",
            memory_type=MemoryType.PROCEDURAL,
            scope=MemoryScope(ScopeKind.TENANT, None, None),
            idempotency_key="foundation-procedure",
        ),
        _principal(TENANT_A, USER_A),
    )
    return result.status is MemoryStatus.NEEDS_REVIEW


async def _automatic_memory_pipeline() -> bool:
    id_values: Iterator[UUID] = iter(
        UUID(f"00000000-0000-0000-0001-{number:012d}") for number in range(1, 8)
    )
    now = datetime(2026, 8, 30, 19, 0, tzinfo=UTC)
    repository = InMemoryEventIngestionRepository(
        new_id=lambda: next(id_values),
        now=lambda: now,
    )
    service = EventIngestionService(repository)
    principal = _principal(TENANT_A, USER_A)
    draft = EventDraft(
        idempotency_key="evaluation-build-failure",
        session_id="evaluation-session",
        sequence_number=1,
        event_type=EventType.TOOL_RESULT,
        agent_id="coding_agent",
        occurred_at=now,
        scope=MemoryScope(ScopeKind.WORKSPACE, WORKSPACE_ID, None),
        payload={
            "tool_name": "build",
            "exit_code": 1,
            "summary": "private build diagnostic",
        },
    )
    command = IngestEventBatchCommand((draft,))
    accepted = await service.ingest_batch(command, principal)
    replay = await service.ingest_batch(command, principal)

    extractor = CodingFailureRuleExtractor()
    dispatcher = OutboxDispatcher(repository, extractor.version)
    dispatched = await dispatcher.dispatch_once(TENANT_A, 10)
    redispatched = await dispatcher.dispatch_once(TENANT_A, 10)
    event = Event(
        tenant_id=TENANT_A,
        event_id=accepted[0].event_id,
        draft=draft,
        actor_user_id=USER_A,
        received_at=now,
    )
    candidates = await extractor.extract(event)
    memories_and_versions = tuple(
        Memory.create(
            tenant_id=TENANT_A,
            memory_id=next(id_values),
            version_id=next(id_values),
            memory_type=candidate.memory_type,
            scope=candidate.scope,
            owner_user_id=USER_A,
            content=candidate.content,
            now=now,
            status=MemoryStatus.CANDIDATE,
            confidence=candidate.confidence,
            utility=candidate.utility,
            authority_level=candidate.authority_level,
            verification_status=candidate.verification_status,
        )
        for candidate in candidates
    )
    evidence = {
        (memory_version.version_id, event.event_id)
        for _, memory_version in memories_and_versions
    }
    counts = (
        repository.event_count,
        repository.outbox_count,
        repository.job_count,
        len(memories_and_versions),
        len(memories_and_versions),
        len(evidence),
    )
    return (
        replay[0].event_id == accepted[0].event_id
        and replay[0].disposition == "duplicate"
        and dispatched == 1
        and redispatched == 0
        and counts == (1, 1, 1, 1, 1, 1)
        and memories_and_versions[0][0].status is MemoryStatus.CANDIDATE
    )


async def run_foundation_evaluation() -> tuple[EvaluationResult, ...]:
    cases: tuple[tuple[str, Callable[[], Awaitable[bool]], str], ...] = (
        ("valid_workspace_memory", _valid_workspace_memory, "VALID_MEMORY_FAILED"),
        ("invalid_scope_combination", _invalid_scope_combination, "INVALID_SCOPE_ACCEPTED"),
        ("idempotent_replay", _idempotent_replay, "IDEMPOTENCY_FAILED"),
        ("stale_revision_rejection", _stale_revision_rejection, "STALE_WRITE_ACCEPTED"),
        ("deleted_memory_exclusion", _deleted_memory_exclusion, "DELETED_MEMORY_HIT"),
        ("tenant_known_id_attack", _tenant_known_id_attack, "TENANT_LEAK"),
        (
            "tenant_procedure_needs_review",
            _tenant_procedure_needs_review,
            "UNREVIEWED_PROCEDURE_ACTIVATED",
        ),
        (
            "automatic_memory_pipeline",
            _automatic_memory_pipeline,
            "AUTOMATIC_MEMORY_PIPELINE_FAILED",
        ),
    )
    results: list[EvaluationResult] = []
    for case_id, evaluation, failure_code in cases:
        try:
            passed = await evaluation()
            results.append(
                EvaluationResult(
                    case_id,
                    passed,
                    "PASS" if passed else failure_code,
                    tenant_leak=case_id == "tenant_known_id_attack" and not passed,
                    deleted_memory_hit=case_id == "deleted_memory_exclusion" and not passed,
                )
            )
        except (MemoryError, RuntimeError, ValueError) as error:
            results.append(
                EvaluationResult(
                    case_id,
                    False,
                    "EVALUATION_ERROR",
                    diagnostic=type(error).__name__,
                )
            )
    return tuple(results)


def report_results(
    results: Sequence[EvaluationResult],
    *,
    stream: TextIO = sys.stdout,
) -> int:
    failed = [result for result in results if not result.passed]
    for result in failed:
        print(f"{result.case_id}:{result.reason_code}", file=stream)
    print(
        "Foundation evaluator: "
        f"total={len(results)} "
        f"passed={len(results) - len(failed)} "
        f"failed={len(failed)} "
        f"tenant_leaks={sum(result.tenant_leak for result in results)} "
        f"deleted_memory_hits={sum(result.deleted_memory_hit for result in results)}",
        file=stream,
    )
    return 1 if failed else 0


def main() -> int:
    return report_results(asyncio.run(run_foundation_evaluation()))


if __name__ == "__main__":
    raise SystemExit(main())
