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


class InvalidEvent(MemoryError):
    pass


class EventIdempotencyConflict(MemoryError):
    pass


class EventSequenceConflict(MemoryError):
    pass


class EventScopeForbidden(MemoryScopeForbidden):
    pass


class LeaseUnavailable(MemoryError):
    pass


class LeaseLost(MemoryError):
    pass
