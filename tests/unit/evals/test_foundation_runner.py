import asyncio
from io import StringIO
from pathlib import Path

import pytest

from agent_memory.evals.foundation_runner import (
    EvaluationResult,
    evaluate_foundation_case,
    report_results,
    run_foundation_evaluation,
)
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


def test_report_returns_failure_and_never_prints_memory_content() -> None:
    output = StringIO()
    results = (
        EvaluationResult("valid_workspace_memory", True, "PASS"),
        EvaluationResult(
            "tenant_known_id_attack",
            False,
            "TENANT_LEAK",
            tenant_leak=True,
            diagnostic="Tenant A private build memory",
        ),
    )

    exit_code = report_results(results, stream=output)

    assert exit_code == 1
    assert "tenant_known_id_attack:TENANT_LEAK" in output.getvalue()
    assert "Tenant A private build memory" not in output.getvalue()


def test_foundation_evaluation_includes_automatic_memory_pipeline() -> None:
    results = asyncio.run(run_foundation_evaluation())

    assert len(results) == 8
    assert any(
        result.case_id == "automatic_memory_pipeline" and result.passed
        for result in results
    )


def test_report_emits_eight_case_summary() -> None:
    output = StringIO()
    results = tuple(
        EvaluationResult(f"case_{number}", True, "PASS") for number in range(8)
    )

    exit_code = report_results(results, stream=output)

    assert exit_code == 0
    assert (
        "Foundation evaluator: total=8 passed=8 failed=0 "
        "tenant_leaks=0 deleted_memory_hits=0"
    ) in output.getvalue()


@pytest.mark.parametrize('error', [KeyError('private-body'), TypeError('private-body'),
                                   AssertionError('private-body'), OSError('private-body')])
async def test_unexpected_case_errors_are_redacted_and_other_cases_continue(monkeypatch, error):
    from agent_memory.evals import foundation_runner

    async def broken():
        raise error

    monkeypatch.setattr(foundation_runner, '_valid_workspace_memory', broken)
    results = await run_foundation_evaluation()
    assert len(results) == 8
    assert results[0].reason_code == 'EVALUATION_ERROR'
    assert results[0].diagnostic == type(error).__name__
    assert all(r.passed for r in results[1:])
    output = StringIO()
    assert report_results(results, stream=output) == 1
    assert 'private-body' not in output.getvalue()


async def test_foundation_does_not_swallow_cancellation(monkeypatch):
    from agent_memory.evals import foundation_runner

    async def cancelled():
        raise asyncio.CancelledError

    monkeypatch.setattr(foundation_runner, '_valid_workspace_memory', cancelled)
    with pytest.raises(asyncio.CancelledError):
        await run_foundation_evaluation()
