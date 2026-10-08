"""Redacted provider failures, including HTTP Retry-After delta/date."""

from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime

import httpx

from agent_memory.domain.errors import MemoryNotFound


def classify(error: Exception, now: datetime) -> tuple[str, bool, timedelta | None]:
    if isinstance(error, MemoryNotFound):
        return "VERSION_NOT_FOUND", False, None
    if isinstance(error, httpx.HTTPStatusError):
        status = error.response.status_code
        delay = None
        if status == 429:
            raw = error.response.headers.get("Retry-After", "")
            try:
                seconds = float(raw)
            except ValueError:
                try:
                    date = parsedate_to_datetime(raw)
                    if date.tzinfo is None:
                        date = date.replace(tzinfo=UTC)
                    seconds = (date - now).total_seconds()
                except (ValueError, TypeError, OverflowError):
                    seconds = 0
            if 0 < seconds <= 86400:
                delay = timedelta(seconds=seconds)
        code = "PROVIDER_CONFIGURATION_ERROR" if status in (401, 403) else f"HTTP_{status}"
        return code, status in (408, 429) or status >= 500, delay
    if isinstance(error, (ValueError, TypeError, IndexError, KeyError, OverflowError)):
        return "INVALID_EMBEDDING", False, None
    return "PROVIDER_TRANSPORT_FAILURE", True, None
