import json
import logging
from uuid import UUID

import pytest
from opentelemetry.sdk.trace import TracerProvider

from agent_memory.observability import get_logger, set_tracer_provider, span
from agent_memory.observability.context import correlation
from agent_memory.observability.fields import UnsafeTelemetryField
from agent_memory.observability.logging import JsonFormatter

TENANT_ID = UUID("40000000-0000-0000-0000-000000000001")


def render(record: logging.LogRecord) -> dict[str, object]:
    payload = JsonFormatter("agent-memory").format(record)
    parsed: dict[str, object] = json.loads(payload)
    return parsed


def test_event_is_rendered_as_one_json_object(caplog: pytest.LogCaptureFixture) -> None:
    logger = get_logger("agent_memory.test")
    with caplog.at_level(logging.INFO):
        logger.event("memory.remember", tenant_id=TENANT_ID, reason_code="MEMORY_CREATED")

    payload = render(caplog.records[-1])
    assert payload["event"] == "memory.remember"
    assert payload["reason_code"] == "MEMORY_CREATED"
    assert payload["tenant_id"] == str(TENANT_ID)
    assert payload["service"] == "agent-memory"


def test_correlation_identifiers_are_attached_without_being_passed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    logger = get_logger("agent_memory.test")
    with caplog.at_level(logging.INFO), correlation(request_id="req-1", tenant_id=TENANT_ID):
        logger.event("http.request", http_status=200)

    payload = render(caplog.records[-1])
    assert payload["request_id"] == "req-1"
    assert payload["tenant_id"] == str(TENANT_ID)


def test_log_lines_carry_the_trace_id_of_the_enclosing_span(
    caplog: pytest.LogCaptureFixture,
) -> None:
    set_tracer_provider(TracerProvider())
    try:
        logger = get_logger("agent_memory.test")
        with caplog.at_level(logging.INFO), span("memory.remember") as current:
            logger.event("memory.remember", reason_code="MEMORY_CREATED")
            expected = format(current.get_span_context().trace_id, "032x")
    finally:
        set_tracer_provider(None)

    assert render(caplog.records[-1])["trace_id"] == expected


def test_logging_memory_content_is_a_type_error_not_a_review_comment() -> None:
    logger = get_logger("agent_memory.test")

    with pytest.raises(UnsafeTelemetryField):
        logger.event("memory.remember", content="deploys fail without --no-cache")


def test_event_name_must_be_a_stable_identifier() -> None:
    logger = get_logger("agent_memory.test")

    with pytest.raises(UnsafeTelemetryField):
        logger.event("stored memory for user 42")


def test_exception_logging_keeps_only_the_error_type(caplog: pytest.LogCaptureFixture) -> None:
    logger = logging.getLogger("agent_memory.test")
    with caplog.at_level(logging.ERROR):
        try:
            raise ValueError("secret content in the message")
        except ValueError:
            logger.exception("boom")

    payload = render(caplog.records[-1])
    assert payload["error_type"] == "ValueError"
    assert "secret content" not in json.dumps(payload)
