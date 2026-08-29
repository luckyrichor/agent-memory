class MemoryError(Exception):
    """Base class for stable domain and application errors."""


class InvalidScope(MemoryError):
    pass


class RevisionConflict(MemoryError):
    pass


class InvalidStatusTransition(MemoryError):
    pass


class MemoryNotFound(MemoryError):
    pass


class MemoryScopeForbidden(MemoryError):
    pass


class IdempotencyConflict(MemoryError):
    pass
