import pytest

from agent_memory.application.extraction_worker import WorkerResult
from agent_memory.workers.extraction import format_worker_result, parse_args


def test_dispatch_requires_tenant_id() -> None:
    with pytest.raises(SystemExit):
        parse_args(["dispatch", "--once"])


def test_work_requires_worker_id() -> None:
    with pytest.raises(SystemExit):
        parse_args(
            [
                "work",
                "--tenant-id",
                "36000000-0000-0000-0000-000000000001",
                "--once",
            ]
        )


@pytest.mark.parametrize("seconds", [0, 61])
def test_poll_interval_is_between_one_and_sixty(seconds: int) -> None:
    with pytest.raises(SystemExit):
        parse_args(
            [
                "dispatch",
                "--tenant-id",
                "36000000-0000-0000-0000-000000000001",
                "--poll-seconds",
                str(seconds),
            ]
        )


def test_once_dispatch_parses_tenant_without_database_side_effect() -> None:
    args = parse_args(
        [
            "dispatch",
            "--tenant-id",
            "36000000-0000-0000-0000-000000000001",
            "--once",
        ]
    )

    assert str(args.tenant_id) == "36000000-0000-0000-0000-000000000001"
    assert args.once is True


def test_worker_failure_output_excludes_event_content() -> None:
    result = WorkerResult(
        job_id=None,
        outcome="dead",
        reason_code="INVALID_EVENT_FOR_EXTRACTION",
    )

    output = format_worker_result(result)

    assert "job_id=none" in output
    assert "reason_code=INVALID_EVENT_FOR_EXTRACTION" in output
    assert "private build diagnostic" not in output
