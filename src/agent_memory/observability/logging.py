"""Structured logging that cannot carry memory content.

The only way to log is :meth:`StructuredLogger.event`, which takes a fixed
event name plus keyword fields validated against
:mod:`agent_memory.observability.fields`.  There is no free-text message
parameter, so the usual leak -- interpolating content into a log line -- has no
syntax available to it.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import UTC, datetime
from typing import Any, Final

from opentelemetry import trace

from agent_memory.observability.context import current_correlation
from agent_memory.observability.fields import AttributeValue, UnsafeTelemetryField, sanitize

FIELDS_ATTRIBUTE: Final = "agent_memory_fields"
EVENT_ATTRIBUTE: Final = "agent_memory_event"
HANDLER_MARKER: Final = "_agent_memory_handler"

_EVENT_NAME = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)*$")


class JsonFormatter(logging.Formatter):
    """Render records as one JSON object per line."""

    def __init__(self, service_name: str) -> None:
        super().__init__()
        self._service_name = service_name

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "service": self._service_name,
            "logger": record.name,
            "event": getattr(record, EVENT_ATTRIBUTE, record.getMessage()),
        }
        # Correlation is captured when the record is emitted, not here:
        # formatting can happen after the context has been torn down.
        payload.update(_span_identifiers())
        payload.update(current_correlation())
        payload.update(getattr(record, FIELDS_ATTRIBUTE, {}))
        if record.exc_info is not None:
            # The type name only; a traceback can quote request payloads.
            payload["error_type"] = record.exc_info[0].__name__ if record.exc_info[0] else "unknown"
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _span_identifiers() -> dict[str, str]:
    context = trace.get_current_span().get_span_context()
    if not context.is_valid:
        return {}
    return {
        "trace_id": trace.format_trace_id(context.trace_id),
        "span_id": trace.format_span_id(context.span_id),
    }


class StructuredLogger:
    """Event logger restricted to allow-listed fields."""

    def __init__(self, name: str) -> None:
        self._logger = logging.getLogger(name)

    def event(self, event: str, **fields: object) -> None:
        self._emit(event, logging.INFO, fields)

    def warning(self, event: str, **fields: object) -> None:
        self._emit(event, logging.WARNING, fields)

    def error(self, event: str, **fields: object) -> None:
        self._emit(event, logging.ERROR, fields)

    def _emit(self, event: str, level: int, fields: dict[str, object]) -> None:
        if not _EVENT_NAME.match(event):
            raise UnsafeTelemetryField(
                f"{event!r} is not a valid event name; use dotted lower_snake_case"
            )
        safe: dict[str, AttributeValue] = sanitize(fields)
        captured: dict[str, AttributeValue] = {
            **_span_identifiers(),
            **current_correlation(),
            **safe,
        }
        self._logger.log(
            level,
            event,
            extra={EVENT_ATTRIBUTE: event, FIELDS_ATTRIBUTE: captured},
        )


def get_logger(name: str) -> StructuredLogger:
    return StructuredLogger(name)


def configure_logging(*, service_name: str, level: str, json_output: bool) -> None:
    """Install the JSON handler on the root logger.

    Only a handler this function installed earlier is removed.  Handlers the
    host process (or a test harness) attached are left alone: reconfiguring
    logging should be idempotent, not a takeover of someone else's setup.
    """
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        JsonFormatter(service_name)
        if json_output
        else logging.Formatter("%(levelname)s %(name)s %(message)s")
    )
    setattr(handler, HANDLER_MARKER, True)
    root = logging.getLogger()
    for existing in list(root.handlers):
        if getattr(existing, HANDLER_MARKER, False):
            root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level.upper())
