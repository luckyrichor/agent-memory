from typing import Protocol


class QueueAdmin(Protocol):
    async def status(
        self, *, job_type: str | None = None, version: str | None = None
    ) -> dict[str, object]: ...
    async def requeue(
        self,
        *,
        job_type: str,
        limit: int,
        old_version: str | None = None,
        new_version: str | None = None,
    ) -> int: ...
    async def rebuild_model(self, model: str, key: str, *, limit: int = 1000) -> int: ...
    async def cleanup_idempotency(self, *, limit: int = 1000) -> int: ...
