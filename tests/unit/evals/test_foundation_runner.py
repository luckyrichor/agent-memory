from pathlib import Path

import pytest

from agent_memory.evals.foundation_runner import evaluate_foundation_case
from agent_memory.evals.schema import FoundationActual, FoundationCase

FIXTURE = Path(__file__).parents[2] / "fixtures" / "golden" / "foundation.jsonl"


def test_foundation_case_requires_tenant_and_scope_match() -> None:
    case = FoundationCase.model_validate_json(FIXTURE.read_text().splitlines()[0])
    actual = FoundationActual(
        tenant_id=case.tenant_id,
        memory_type=case.expected_memory_type,
        scope_kind=case.expected_scope_kind,
        content=case.expected_content,
        status="active",
    )

    assert evaluate_foundation_case(case, actual).passed is True

    with pytest.raises(ValueError, match="tenant mismatch"):
        evaluate_foundation_case(
            case,
            actual.model_copy(update={"tenant_id": "00000000-0000-0000-0000-00000000000b"}),
        )
