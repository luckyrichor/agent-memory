import hashlib
import json
from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from agent_memory.application.commands import (
    CorrectMemoryCommand,
    DisableMemoryCommand,
    MemoryResult,
    RememberMemoryCommand,
)
from agent_memory.application.ports import (
    AuditEntry,
    AuditSink,
    IdempotencyRecord,
    IdempotencyRepository,
    MemoryRecord,
    MemoryRepository,
)
from agent_memory.domain.enums import MemoryStatus, MemoryType, ScopeKind
from agent_memory.domain.errors import (
    IdempotencyConflict,
    MemoryNotFound,
    MemoryScopeForbidden,
)
from agent_memory.domain.models import Memory, MemoryScope
from agent_memory.domain.principal import RequestPrincipal
from agent_memory.observability import annotate, get_logger, record_operation, span

_logger = get_logger("agent_memory.application.memory")


class ExplicitMemoryService:
    def __init__(
        self,
        *,
        memory_repository: MemoryRepository,
        idempotency_repository: IdempotencyRepository,
        audit_sink: AuditSink,
        new_id: Callable[[], UUID],
        now: Callable[[], datetime],
    ) -> None:
        self._memories = memory_repository
        self._idempotency = idempotency_repository
        self._audit = audit_sink
        self._new_id = new_id
        self._now = now

    async def remember(
        self,
        command: RememberMemoryCommand,
        principal: RequestPrincipal,
    ) -> MemoryResult:
        request_hash = self._remember_hash(command)
        with span(
            "memory.remember",
            action="memory.remember",
            tenant_id=principal.tenant_id,
            actor_id=principal.user_id,
            memory_type=command.memory_type.value,
            scope_kind=command.scope.kind.value,
        ):
            return await self._remember(command, principal, request_hash)

    async def _remember(
        self,
        command: RememberMemoryCommand,
        principal: RequestPrincipal,
        request_hash: str,
    ) -> MemoryResult:
        try:
            self._authorize_scope(principal, command.scope, "memory:write")
            existing = await self._idempotency.get(principal.tenant_id, command.idempotency_key)
            if existing is not None:
                if existing.request_hash != request_hash:
                    raise IdempotencyConflict(command.idempotency_key)
                await self._record_audit(
                    principal,
                    "memory.remember",
                    "allow",
                    "IDEMPOTENT_REPLAY",
                    existing.result.memory_id,
                )
                self._observe(
                    "memory.remember",
                    "allow",
                    "IDEMPOTENT_REPLAY",
                    memory_id=existing.result.memory_id,
                )
                return existing.result

            status = self._activation_status(command, principal)
            memory, version = Memory.create(
                tenant_id=principal.tenant_id,
                memory_id=self._new_id(),
                version_id=self._new_id(),
                memory_type=command.memory_type,
                scope=command.scope,
                owner_user_id=principal.user_id,
                content=command.content,
                now=self._now(),
                status=status,
            )
            result = MemoryResult(
                memory_id=memory.memory_id,
                version_id=version.version_id,
                revision=memory.revision,
                status=memory.status,
            )
            await self._memories.add(principal.tenant_id, memory, version)
            await self._idempotency.save(
                principal.tenant_id,
                command.idempotency_key,
                IdempotencyRecord(request_hash, result),
            )
            await self._record_audit(
                principal,
                "memory.remember",
                "allow",
                "MEMORY_CREATED",
                memory.memory_id,
            )
            self._observe(
                "memory.remember",
                "allow",
                "MEMORY_CREATED",
                memory_id=memory.memory_id,
                memory_status=memory.status.value,
            )
            return result
        except (IdempotencyConflict, MemoryScopeForbidden) as error:
            reason = (
                "IDEMPOTENCY_CONFLICT"
                if isinstance(error, IdempotencyConflict)
                else "MEMORY_SCOPE_FORBIDDEN"
            )
            await self._record_audit(
                principal,
                "memory.remember",
                "deny",
                reason,
                None,
            )
            self._observe("memory.remember", "deny", reason)
            raise

    async def get_active(self, memory_id: UUID, principal: RequestPrincipal) -> MemoryRecord:
        with span(
            "memory.get_active",
            action="memory.get_active",
            tenant_id=principal.tenant_id,
            actor_id=principal.user_id,
            memory_id=memory_id,
        ):
            record = await self._required_record(memory_id, principal)
            self._authorize_scope(principal, record.memory.scope, "memory:read")
            if record.memory.status is not MemoryStatus.ACTIVE:
                self._observe("memory.get_active", "deny", "MEMORY_NOT_ACTIVE", memory_id=memory_id)
                raise MemoryNotFound(str(memory_id))
            self._observe(
                "memory.get_active",
                "allow",
                "MEMORY_RETURNED",
                memory_id=memory_id,
                memory_status=record.memory.status.value,
                version_number=record.current_version.version_number,
            )
            return record

    async def correct(
        self,
        command: CorrectMemoryCommand,
        principal: RequestPrincipal,
    ) -> MemoryResult:
        with span(
            "memory.correct",
            action="memory.correct",
            tenant_id=principal.tenant_id,
            actor_id=principal.user_id,
            memory_id=command.memory_id,
            revision=command.expected_revision,
        ):
            return await self._correct(command, principal)

    async def _correct(
        self,
        command: CorrectMemoryCommand,
        principal: RequestPrincipal,
    ) -> MemoryResult:
        record = await self._required_record(command.memory_id, principal)
        self._authorize_scope(principal, record.memory.scope, "memory:write")
        updated, version = record.memory.add_version(
            version_id=self._new_id(),
            content=command.content,
            expected_revision=command.expected_revision,
            now=self._now(),
        )
        await self._memories.append_version(
            principal.tenant_id,
            updated,
            version,
            command.expected_revision,
        )
        await self._record_audit(
            principal,
            "memory.correct",
            "allow",
            "MEMORY_VERSION_CREATED",
            updated.memory_id,
        )
        self._observe(
            "memory.correct",
            "allow",
            "MEMORY_VERSION_CREATED",
            memory_id=updated.memory_id,
            version_number=version.version_number,
            revision=updated.revision,
        )
        return MemoryResult(
            updated.memory_id,
            version.version_id,
            updated.revision,
            updated.status,
        )

    async def disable(
        self,
        command: DisableMemoryCommand,
        principal: RequestPrincipal,
    ) -> MemoryResult:
        with span(
            "memory.disable",
            action="memory.disable",
            tenant_id=principal.tenant_id,
            actor_id=principal.user_id,
            memory_id=command.memory_id,
            memory_status=command.status.value,
        ):
            return await self._disable(command, principal)

    async def _disable(
        self,
        command: DisableMemoryCommand,
        principal: RequestPrincipal,
    ) -> MemoryResult:
        record = await self._required_record(command.memory_id, principal)
        self._authorize_scope(principal, record.memory.scope, "memory:delete")
        updated = record.memory.disable(command.status, self._now())
        await self._memories.disable(
            principal.tenant_id,
            updated,
            command.expected_revision,
        )
        await self._record_audit(
            principal,
            "memory.disable",
            "allow",
            f"MEMORY_{command.status.value.upper()}",
            command.memory_id,
        )
        self._observe(
            "memory.disable",
            "allow",
            f"MEMORY_{command.status.value.upper()}",
            memory_id=command.memory_id,
            memory_status=updated.status.value,
        )
        return MemoryResult(
            updated.memory_id,
            updated.current_version_id,
            updated.revision,
            updated.status,
        )

    @staticmethod
    def _observe(action: str, decision: str, reason_code: str, **fields: object) -> None:
        """Emit the three signals for one outcome: span, log line, counter."""
        annotate(decision=decision, reason_code=reason_code, **fields)
        _logger.event(action, decision=decision, reason_code=reason_code, **fields)
        record_operation(action=action, decision=decision, reason_code=reason_code)

    async def _required_record(
        self,
        memory_id: UUID,
        principal: RequestPrincipal,
    ) -> MemoryRecord:
        record = await self._memories.get(principal.tenant_id, memory_id)
        if record is None:
            raise MemoryNotFound(str(memory_id))
        return record

    @staticmethod
    def _activation_status(
        command: RememberMemoryCommand,
        principal: RequestPrincipal,
    ) -> MemoryStatus:
        high_risk_tenant_procedure = (
            command.memory_type is MemoryType.PROCEDURAL
            and command.scope.kind is ScopeKind.TENANT
            and "memory:admin" not in principal.permissions
        )
        return MemoryStatus.NEEDS_REVIEW if high_risk_tenant_procedure else MemoryStatus.ACTIVE

    @staticmethod
    def _authorize_scope(
        principal: RequestPrincipal,
        scope: MemoryScope,
        required_permission: str,
    ) -> None:
        if required_permission not in principal.permissions:
            raise MemoryScopeForbidden(required_permission)
        if scope.kind in {
            ScopeKind.WORKSPACE,
            ScopeKind.USER_WORKSPACE,
        } and not principal.can_access_workspace(scope.workspace_id):
            raise MemoryScopeForbidden(scope.workspace_id or "missing workspace")
        if (
            scope.kind in {ScopeKind.USER_GLOBAL, ScopeKind.USER_WORKSPACE}
            and scope.subject_user_id != principal.user_id
            and "memory:admin" not in principal.permissions
        ):
            raise MemoryScopeForbidden(str(scope.subject_user_id))

    @staticmethod
    def _remember_hash(command: RememberMemoryCommand) -> str:
        payload = {
            "content": command.content,
            "memory_type": command.memory_type.value,
            "scope_kind": command.scope.kind.value,
            "subject_user_id": (
                str(command.scope.subject_user_id) if command.scope.subject_user_id else None
            ),
            "workspace_id": command.scope.workspace_id,
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
        return hashlib.sha256(encoded).hexdigest()

    async def _record_audit(
        self,
        principal: RequestPrincipal,
        action: str,
        decision: str,
        reason_code: str,
        resource_id: UUID | None,
    ) -> None:
        await self._audit.record(
            AuditEntry(
                tenant_id=principal.tenant_id,
                actor_id=principal.user_id,
                action=action,
                decision=decision,
                reason_code=reason_code,
                resource_id=resource_id,
            )
        )
