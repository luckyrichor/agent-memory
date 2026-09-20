from agent_memory.application.event_commands import (
    EventIngestionResult,
    IngestEventBatchCommand,
)
from agent_memory.application.event_ports import EventIngestionRepository
from agent_memory.domain.enums import ScopeKind
from agent_memory.domain.errors import EventScopeForbidden, InvalidEvent
from agent_memory.domain.models import MemoryScope
from agent_memory.domain.principal import RequestPrincipal
from agent_memory.observability import annotate, get_logger, span

_logger = get_logger("agent_memory.application.events")


class EventIngestionService:
    def __init__(self, repository: EventIngestionRepository) -> None:
        self._repository = repository

    async def ingest_batch(
        self,
        command: IngestEventBatchCommand,
        principal: RequestPrincipal,
    ) -> tuple[EventIngestionResult, ...]:
        with span(
            "events.ingest_batch",
            action="events.ingest_batch",
            tenant_id=principal.tenant_id,
            actor_id=principal.user_id,
            batch_size=len(command.drafts),
        ):
            if not 1 <= len(command.drafts) <= 100:
                raise InvalidEvent("event batch size must be between 1 and 100")
            for draft in command.drafts:
                self._authorize_scope(principal, draft.scope)
            results = await self._repository.ingest_batch(
                principal.tenant_id,
                principal.user_id,
                command.drafts,
            )
            annotate(event_count=len(results), reason_code="EVENTS_INGESTED")
            _logger.event(
                "events.ingested",
                tenant_id=principal.tenant_id,
                actor_id=principal.user_id,
                batch_size=len(command.drafts),
                event_count=len(results),
            )
            return results

    @staticmethod
    def _authorize_scope(principal: RequestPrincipal, scope: MemoryScope) -> None:
        if "memory:write" not in principal.permissions:
            raise EventScopeForbidden("memory:write")
        if scope.kind in {ScopeKind.WORKSPACE, ScopeKind.USER_WORKSPACE} and not (
            principal.can_access_workspace(scope.workspace_id)
        ):
            raise EventScopeForbidden(scope.workspace_id or "missing workspace")
        if (
            scope.kind in {ScopeKind.USER_GLOBAL, ScopeKind.USER_WORKSPACE}
            and scope.subject_user_id != principal.user_id
            and "memory:admin" not in principal.permissions
        ):
            raise EventScopeForbidden(str(scope.subject_user_id))
