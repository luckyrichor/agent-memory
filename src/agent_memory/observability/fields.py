"""Allow-list of telemetry field names.

Observability is the one place where memory content is most likely to leak: a
careless ``logger.info(f"stored {content}")`` defeats every access control in
the system.  Instead of relying on discipline, this module makes the leak
structurally impossible -- there is no approved field name for free text, and
any attempt to attach an unknown field raises :class:`UnsafeTelemetryField`.

Anything not listed here cannot be logged, traced or measured.  Adding a field
is a deliberate edit to this file, reviewed like any other change.
"""

from __future__ import annotations

from uuid import UUID

#: Identifiers.  Opaque values that cannot carry user content.
IDENTITY_FIELDS: frozenset[str] = frozenset(
    {
        "actor_id",
        "event_id",
        "job_id",
        "memory_id",
        "request_id",
        "session_id",
        "tenant_id",
        "version_id",
        "worker_id",
    }
)

#: Closed vocabularies: enum values, reason codes, route templates.
CLASSIFICATION_FIELDS: frozenset[str] = frozenset(
    {
        "action",
        "decision",
        "error_type",
        "extractor_version",
        "http_method",
        "http_status",
        "memory_status",
        "memory_type",
        "outcome",
        "reason_code",
        "route",
        "scope_kind",
        "service",
    }
)

#: Numbers.  Counts and durations, never a payload size stand-in for content.
MEASURE_FIELDS: frozenset[str] = frozenset(
    {
        "attempt",
        "batch_size",
        "candidate_count",
        "count",
        "duration_ms",
        "event_count",
        "revision",
        "sequence",
        "version_number",
    }
)

ALLOWED_FIELDS: frozenset[str] = IDENTITY_FIELDS | CLASSIFICATION_FIELDS | MEASURE_FIELDS

#: Upper bound for string values.  Reason codes and identifiers are short; a
#: long string is a sign that content slipped into an approved field name.
MAX_STRING_LENGTH = 64

AttributeValue = str | int | float | bool


class UnsafeTelemetryField(ValueError):
    """Raised when a telemetry field is not on the allow-list or is too long."""


def sanitize(fields: dict[str, object]) -> dict[str, AttributeValue]:
    """Validate *fields* and normalise values to OpenTelemetry attribute types.

    Raises :class:`UnsafeTelemetryField` for unknown names, unsupported value
    types, and strings long enough to plausibly be memory content.
    """
    sanitized: dict[str, AttributeValue] = {}
    for key, value in fields.items():
        if key not in ALLOWED_FIELDS:
            raise UnsafeTelemetryField(
                f"{key!r} is not an approved telemetry field; "
                "add it to observability/fields.py if it carries no content"
            )
        if value is None:
            continue
        sanitized[key] = _sanitize_value(key, value)
    return sanitized


def _sanitize_value(key: str, value: object) -> AttributeValue:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        if len(value) > MAX_STRING_LENGTH:
            raise UnsafeTelemetryField(
                f"{key!r} exceeds {MAX_STRING_LENGTH} characters; "
                "telemetry carries identifiers and reason codes, not text"
            )
        return value
    raise UnsafeTelemetryField(
        f"{key!r} has unsupported type {type(value).__name__}; "
        "telemetry accepts UUID, str, int, float and bool"
    )
