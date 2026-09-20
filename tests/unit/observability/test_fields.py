import uuid

import pytest

from agent_memory.observability.fields import (
    ALLOWED_FIELDS,
    MAX_STRING_LENGTH,
    UnsafeTelemetryField,
    sanitize,
)


def test_identifiers_are_normalised_to_strings() -> None:
    tenant_id = uuid.UUID("40000000-0000-0000-0000-000000000001")

    assert sanitize({"tenant_id": tenant_id}) == {"tenant_id": str(tenant_id)}


def test_none_values_are_dropped_rather_than_exported() -> None:
    assert sanitize({"job_id": None, "count": 0}) == {"count": 0}


def test_unknown_field_is_rejected() -> None:
    with pytest.raises(UnsafeTelemetryField):
        sanitize({"content": "the user prefers dark mode"})


@pytest.mark.parametrize("field", ["content", "payload", "message", "text", "body", "draft"])
def test_no_field_name_exists_for_free_text(field: str) -> None:
    """The leak is prevented by vocabulary: there is no approved place to put it."""
    assert field not in ALLOWED_FIELDS


def test_long_string_in_an_approved_field_is_rejected() -> None:
    with pytest.raises(UnsafeTelemetryField):
        sanitize({"reason_code": "x" * (MAX_STRING_LENGTH + 1)})


def test_unsupported_value_type_is_rejected() -> None:
    with pytest.raises(UnsafeTelemetryField):
        sanitize({"count": {"nested": "structure"}})
