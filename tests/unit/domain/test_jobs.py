from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from agent_memory.domain.errors import LeaseLost, LeaseUnavailable
from agent_memory.domain.jobs import Job, JobStatus

TENANT_ID = UUID("00000000-0000-0000-0000-00000000000a")
JOB_ID = UUID("00000000-0000-0000-0000-00000000000b")
NOW = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)


def pending_job(*, attempts: int = 0, max_attempts: int = 5) -> Job:
    return Job(
        tenant_id=TENANT_ID,
        job_id=JOB_ID,
        job_type="extract_event",
        idempotency_key="extract:event-1:coding-failure-rule-v1",
        payload={"event_id": "event-1", "extractor_version": "coding-failure-rule-v1"},
        status=JobStatus.PENDING,
        attempts=attempts,
        max_attempts=max_attempts,
        available_at=NOW,
        leased_until=None,
        lease_owner=None,
        last_error_code=None,
        created_at=NOW,
        updated_at=NOW,
    )


def test_claim_sets_owner_lease_and_attempt() -> None:
    claimed = pending_job().claim("worker-a", NOW, timedelta(seconds=30))

    assert claimed.status is JobStatus.RUNNING
    assert claimed.lease_owner == "worker-a"
    assert claimed.leased_until == NOW + timedelta(seconds=30)
    assert claimed.attempts == 1


def test_active_lease_cannot_be_stolen_but_expired_lease_can_be_reclaimed() -> None:
    claimed = pending_job().claim("worker-a", NOW, timedelta(seconds=30))

    with pytest.raises(LeaseUnavailable):
        claimed.claim("worker-b", NOW + timedelta(seconds=29), timedelta(seconds=30))

    reclaimed = claimed.claim("worker-b", NOW + timedelta(seconds=31), timedelta(seconds=30))
    assert reclaimed.lease_owner == "worker-b"
    assert reclaimed.attempts == 2


def test_only_lease_owner_can_renew_or_finish() -> None:
    claimed = pending_job().claim("worker-a", NOW, timedelta(seconds=30))

    with pytest.raises(LeaseLost):
        claimed.renew("worker-b", NOW, timedelta(seconds=30))
    with pytest.raises(LeaseLost):
        claimed.succeed("worker-b", NOW)

    renewed = claimed.renew("worker-a", NOW + timedelta(seconds=10), timedelta(seconds=30))
    assert renewed.leased_until == NOW + timedelta(seconds=40)
    assert renewed.succeed("worker-a", NOW + timedelta(seconds=11)).status is JobStatus.SUCCEEDED


def test_transient_failure_uses_deterministic_backoff() -> None:
    claimed = pending_job().claim("worker-a", NOW, timedelta(seconds=30))

    failed = claimed.fail("worker-a", NOW, "EXTRACTOR_UNAVAILABLE", retryable=True)

    assert failed.status is JobStatus.RETRY_WAIT
    assert failed.available_at == NOW + timedelta(seconds=2)
    assert failed.last_error_code == "EXTRACTOR_UNAVAILABLE"
    assert failed.lease_owner is None


def test_max_attempts_or_permanent_failure_moves_job_to_dead() -> None:
    exhausted = pending_job(attempts=4, max_attempts=5).claim(
        "worker-a", NOW, timedelta(seconds=30)
    )
    permanent = pending_job().claim("worker-b", NOW, timedelta(seconds=30))

    assert exhausted.fail("worker-a", NOW, "TEMPORARY", retryable=True).status is JobStatus.DEAD
    assert permanent.fail("worker-b", NOW, "INVALID_EVENT", retryable=False).status is JobStatus.DEAD
