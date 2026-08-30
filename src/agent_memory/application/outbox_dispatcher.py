from uuid import UUID

from agent_memory.application.event_ports import OutboxDispatchRepository
from agent_memory.domain.errors import InvalidEvent


class OutboxDispatcher:
    def __init__(
        self,
        repository: OutboxDispatchRepository,
        extractor_version: str,
    ) -> None:
        self._repository = repository
        self._extractor_version = extractor_version

    async def dispatch_once(self, tenant_id: UUID, batch_size: int) -> int:
        if not 1 <= batch_size <= 100:
            raise InvalidEvent("outbox batch size must be between 1 and 100")
        return await self._repository.dispatch_once(
            tenant_id,
            batch_size,
            self._extractor_version,
        )
