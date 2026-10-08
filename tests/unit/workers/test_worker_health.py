from uuid import uuid4

from agent_memory.workers.health import check, heartbeat


def test_health_checks_age_process_and_sticky_configuration_failure(monkeypatch, tmp_path):
    monkeypatch.setenv("MEMORY_WORKER_HEALTH_DIR", str(tmp_path))
    tenant = uuid4()
    assert not check(tenant, "w", "embedding", 60)
    heartbeat(tenant, "w", "embedding", "EMBEDDING_SUCCEEDED")
    assert check(tenant, "w", "embedding", 60)
    assert not check(uuid4(), "w", "embedding", 60)
    assert not check(tenant, "w", "embedding", 0)
    heartbeat(tenant, "w", "embedding", "PROVIDER_CONFIGURATION_ERROR")
    heartbeat(tenant, "w", "embedding", "NO_JOB_AVAILABLE")
    assert not check(tenant, "w", "embedding", 60)
    heartbeat(tenant, "w", "embedding", "EMBEDDING_SUCCEEDED")
    assert check(tenant, "w", "embedding", 60)
