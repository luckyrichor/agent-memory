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


class RetryableExtractionError(MemoryError):
    def __init__(self, code: str = "EXTRACTION_FAILED") -> None:
        import re

        self.code = code if re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", code) else "EXTRACTION_FAILED"
        super().__init__(code)


class ExtractorVersionMismatch(InvalidEvent):
    pass


class ContentRejected(MemoryError):
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
