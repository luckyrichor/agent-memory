import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError

from agent_memory.application.commands import CorrectMemoryCommand, RememberMemoryCommand
from agent_memory.application.embedding import EmbeddingWorker
from agent_memory.application.explicit_memory import ExplicitMemoryService
from agent_memory.application.extraction_worker import ExtractionWorker
from agent_memory.config import Settings
from agent_memory.domain.content_policy import sensitive
from agent_memory.domain.enums import MemoryType, ScopeKind
from agent_memory.domain.errors import ContentRejected
from agent_memory.domain.events import Event, EventDraft, EventType
from agent_memory.domain.jobs import Job, JobStatus
from agent_memory.domain.models import MemoryScope
from agent_memory.domain.principal import RequestPrincipal
from agent_memory.infrastructure.embedding import HTTPEmbeddingProvider
from agent_memory.infrastructure.in_memory import (
    InMemoryAuditSink,
    InMemoryIdempotencyRepository,
    InMemoryMemoryRepository,
)
from agent_memory.infrastructure.in_memory_embedding import InMemoryEmbeddingBackend
from agent_memory.infrastructure.llm_extractor import LLMExtractor
from agent_memory.infrastructure.query_vectors import QueryVectors


async def test_429_then_success_retries_non_build_event_without_losing_candidate() -> None:
    now = datetime.now(UTC)
    tenant, user, event_id, job_id = (uuid4() for _ in range(4))
    calls = 0

    def endpoint(request):
        nonlocal calls
        calls += 1
        return (
            httpx.Response(429)
            if calls == 1
            else httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "memories": [
                                            {"content": "Check configuration before deploying"}
                                        ]
                                    }
                                )
                            }
                        }
                    ]
                },
            )
        )

    model = LLMExtractor(
        "https://test.invalid/chat", "fixture", "test", transport=httpx.MockTransport(endpoint)
    )
    event = Event(
        tenant,
        event_id,
        EventDraft(
            "e",
            "s",
            1,
            EventType.TASK_COMPLETED,
            "agent",
            now,
            MemoryScope(ScopeKind.WORKSPACE, "p", None),
            {"summary": "Check configuration before deployment"},
        ),
        user,
        now,
    )

    class Backend:
        job = Job(
            tenant,
            job_id,
            "extract_event",
            "e",
            {"event_id": str(event_id), "extractor_version": model.version},
            JobStatus.PENDING,
            0,
            5,
            now,
            None,
            None,
            None,
            now,
            now,
        )
        candidates = ()

        async def claim(self, tenant, worker, at, duration):
            self.job = self.job.claim(worker, at, duration)
            return self.job

        async def load_event(self, tenant, event_id):
            return event

        async def fail_job(self, tenant, job_id, worker, at, code, *, retryable):
            self.job = self.job.fail(worker, at, code, retryable=retryable)
            return self.job

        async def commit_candidates(self, tenant, job, worker, event, candidates, at):
            self.candidates = candidates
            self.job = replace(job.succeed(worker, at), payload=dict(job.payload))

    backend = Backend()
    clock = [now]
    worker = ExtractionWorker(
        backend, model, now=lambda: clock[0], lease_duration=timedelta(seconds=30)
    )
    first = await worker.run_once(tenant, "w")
    assert first.outcome == "retry_wait" and first.reason_code == "HTTP_429"
    assert backend.candidates == () and backend.job.status == JobStatus.RETRY_WAIT
    clock[0] += timedelta(seconds=2)
    second = await worker.run_once(tenant, "w")
    assert second.outcome == "succeeded" and second.reason_code == "LLM_EXTRACTED"
    assert len(backend.candidates) == 1 and backend.job.attempts == 2
    assert backend.job.payload["extraction_reason"] == "LLM_EXTRACTED"


@pytest.mark.parametrize(
    "status, outcome, code",
    [
        (400, "dead", "HTTP_400"),
        (401, "dead", "PROVIDER_CONFIGURATION_ERROR"),
        (403, "dead", "PROVIDER_CONFIGURATION_ERROR"),
        (429, "retry_wait", "HTTP_429"),
        (503, "retry_wait", "HTTP_503"),
    ],
)
async def test_embedding_error_classification_and_retry_after(status, outcome, code) -> None:
    backend = InMemoryEmbeddingBackend()
    tenant, version = uuid4(), uuid4()
    now = datetime.now(UTC)
    await backend.enqueue(tenant, version, "text", now)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(status, headers={"Retry-After": "120"})
        )
    ) as http:
        provider = HTTPEmbeddingProvider(
            http, endpoint="https://test.invalid/embed", model="test", token="test"
        )
        result = await EmbeddingWorker(backend, provider).run_once(tenant, "w", now=now)
    assert result.outcome == outcome and result.reason_code == code
    job = next(iter(backend.jobs.values()))
    assert job.attempts == 1
    if status == 429:
        assert job.available_at == now + timedelta(seconds=120)


async def test_missing_embedding_version_is_permanent() -> None:
    backend = InMemoryEmbeddingBackend()
    tenant, version = uuid4(), uuid4()
    now = datetime.now(UTC)
    await backend.enqueue(tenant, version, "text", now)
    backend.contents.clear()
    from agent_memory.infrastructure.embedding import FixtureEmbeddingProvider

    result = await EmbeddingWorker(backend, FixtureEmbeddingProvider()).run_once(
        tenant, "w", now=now
    )
    assert result.outcome == "dead" and result.reason_code == "VERSION_NOT_FOUND"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"extraction_timeout_seconds": 30},
        {"embedding_timeout_seconds": 25},
        {"worker_lease_seconds": 10},
    ],
)
def test_timeout_must_fit_lease_with_commit_margin(kwargs) -> None:
    with pytest.raises(ValidationError):
        Settings(**kwargs)


@pytest.mark.parametrize(
    "text",
    [
        "身份证 11010519491231002X",
        "卡号 4111 1111 1111 1111",
        "ghp_abcdefgh1234567890",
        "xoxb-123456789abcdef",
        "ＡＰＩ＿ＫＥＹ=foo",
        "pass\u200bword=foo",
        "eyJabc.eyJdef.abcd",
        "-----BEGIN PRIVATE KEY-----",
    ],
)
def test_sensitive_variants(text) -> None:
    assert sensitive(text)


async def test_explicit_writes_and_reasons_share_policy_and_reason_is_audited() -> None:
    tenant, user = uuid4(), uuid4()
    principal = RequestPrincipal(
        tenant, user, frozenset(), frozenset({"memory:write", "memory:read"}), frozenset()
    )
    memories, audit = InMemoryMemoryRepository(), InMemoryAuditSink()
    service = ExplicitMemoryService(
        memory_repository=memories,
        idempotency_repository=InMemoryIdempotencyRepository(),
        audit_sink=audit,
        new_id=uuid4,
        now=lambda: datetime.now(UTC),
    )
    command = RememberMemoryCommand(
        "Use Java 17", MemoryType.SEMANTIC, MemoryScope(ScopeKind.TENANT, None, None), "k"
    )
    with pytest.raises(ContentRejected):
        await service.remember(replace(command, content="password=abc"), principal)
    created = await service.remember(command, principal)
    with pytest.raises(ContentRejected):
        await service.correct(
            CorrectMemoryCommand(created.memory_id, 1, "Use Java 21", "API_KEY=abc"), principal
        )
    await service.correct(
        CorrectMemoryCommand(created.memory_id, 1, "Use Java 21", "Runtime upgraded"), principal
    )
    versions, next_offset = await service.versions(created.memory_id, principal, 1, 1)
    assert versions[0].reason == "Runtime upgraded" and next_offset is None
    assert audit.entries[-1].reason == "Runtime upgraded"


async def test_idempotency_expires_after_seven_days() -> None:
    from agent_memory.application.commands import MemoryResult
    from agent_memory.application.ports import IdempotencyRecord
    from agent_memory.domain.enums import MemoryStatus

    now = [datetime.now(UTC)]
    repo = InMemoryIdempotencyRepository(lambda: now[0])
    tenant = uuid4()
    record = IdempotencyRecord("hash", MemoryResult(uuid4(), uuid4(), 1, MemoryStatus.ACTIVE))
    await repo.save(tenant, "key", record)
    now[0] += timedelta(days=7, seconds=-1)
    assert await repo.get(tenant, "key") == record
    now[0] += timedelta(seconds=1)
    assert await repo.get(tenant, "key") is None
    await repo.save(tenant, "key", record)
    assert await repo.get(tenant, "key") == record


async def test_query_cache_tenant_isolation_expiry_and_concurrency(monkeypatch) -> None:
    cache = QueryVectors(
        Settings(
            embedding_model="m",
            embedding_endpoint="https://test.invalid/e",
            query_embedding_concurrency=1,
            query_embedding_cache_seconds=0.01,
        )
    )
    active = peak = calls = 0

    async def endpoint(request):
        nonlocal active, peak, calls
        calls += 1
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.005)
        active -= 1
        return httpx.Response(200, json={"data": [{"embedding": [1.0] * 1024}]})

    cache._client = httpx.AsyncClient(transport=httpx.MockTransport(endpoint))
    a, b = uuid4(), uuid4()
    try:
        assert (await cache.embed(a, "q"))[1] == "provider"
        assert (await cache.embed(a, "q"))[1] == "cache"
        assert (await cache.embed(b, "q"))[1] == "provider"
        await asyncio.sleep(0.02)
        assert (await cache.embed(a, "q"))[1] == "provider"
        await asyncio.gather(cache.embed(a, "r"), cache.embed(a, "s"))
        assert peak == 1 and calls == 5
        assert all("q" not in key[1] for key in cache._cache)
    finally:
        await cache.aclose()


async def test_query_embedding_has_total_timeout() -> None:
    cache = QueryVectors(
        Settings(
            embedding_model="m",
            embedding_endpoint="https://test.invalid/e",
            query_embedding_timeout_seconds=0.01,
        )
    )

    async def endpoint(request):
        await asyncio.sleep(1)
        return httpx.Response(200)

    cache._client = httpx.AsyncClient(transport=httpx.MockTransport(endpoint))
    try:
        with pytest.raises(TimeoutError):
            await cache.embed(uuid4(), "q")
        assert not cache._cache
    finally:
        await cache.aclose()


@pytest.mark.parametrize("has_rule_candidate, outcome", [(True, "succeeded"), (False, "dead")])
async def test_exhausted_transient_failure_only_succeeds_with_actual_rule_candidate(
    has_rule_candidate, outcome
):
    from test_extraction_worker import NOW, TENANT_ID, RecordingBackend
    from test_llm_extractor import event as example_event

    model = LLMExtractor(
        "https://test.invalid/chat",
        "fixture",
        "test",
        transport=httpx.MockTransport(lambda _: httpx.Response(429)),
    )

    class Backend(RecordingBackend):
        async def load_event(self, tenant, event_id):
            original = example_event()
            return replace(
                original,
                draft=replace(
                    original.draft,
                    payload=dict(original.draft.payload)
                    if has_rule_candidate
                    else {"summary": "Check deployment configuration"},
                ),
            )

        async def commit_candidates(self, tenant, job, worker, event, candidates, at):
            assert candidates
            self.job = job.succeed(worker, at)

    backend = Backend()
    backend.job = replace(
        backend.job,
        max_attempts=1,
        payload={**backend.job.payload, "extractor_version": model.version},
    )
    result = await ExtractionWorker(
        backend, model, now=lambda: NOW, lease_duration=timedelta(seconds=30)
    ).run_once(TENANT_ID, "w")
    assert result.outcome == outcome, result
    assert result.reason_code == ("RULE_FALLBACK_EXHAUSTED" if has_rule_candidate else "HTTP_429")


async def test_lost_lease_while_marking_extraction_failure_does_not_crash_worker():
    from test_extraction_worker import NOW, TENANT_ID, FailingExtractor, RecordingBackend

    from agent_memory.domain.errors import LeaseLost

    class Backend(RecordingBackend):
        async def fail_job(self, *args, **kwargs):
            raise LeaseLost("redacted")

    result = await ExtractionWorker(
        Backend(), FailingExtractor(), now=lambda: NOW, lease_duration=timedelta(seconds=30)
    ).run_once(TENANT_ID, "w")
    assert result.outcome == "lease_lost"


def test_retry_after_http_date_and_transport_classification():
    from email.utils import format_datetime

    from agent_memory.application.provider_errors import classify

    at = datetime.now(UTC).replace(microsecond=0)
    response = httpx.Response(
        429,
        headers={"Retry-After": format_datetime(at + timedelta(seconds=90))},
        request=httpx.Request("POST", "https://test.invalid"),
    )
    error = httpx.HTTPStatusError(
        "private provider message", request=response.request, response=response
    )
    assert classify(error, at) == ("HTTP_429", True, timedelta(seconds=90))
    assert classify(httpx.ConnectError("private connection message"), at) == (
        "PROVIDER_TRANSPORT_FAILURE",
        True,
        None,
    )


def test_superseded_link_survives_and_archive_restore_are_rejected():
    from agent_memory.domain.enums import MemoryStatus
    from agent_memory.domain.errors import InvalidStatusTransition
    from agent_memory.domain.models import Memory

    now = datetime.now(UTC)
    memory = Memory(
        tenant_id=uuid4(),
        memory_id=uuid4(),
        memory_type=MemoryType.EPISODIC,
        status=MemoryStatus.ACTIVE,
        owner_user_id=uuid4(),
        current_version_id=uuid4(),
        revision=1,
        scope=MemoryScope(ScopeKind.WORKSPACE, "p", None),
        created_at=now,
        updated_at=now,
    )
    successor = uuid4()
    superseded = memory.disable(MemoryStatus.SUPERSEDED, now, successor)
    assert superseded.successor_id == successor
    with pytest.raises(InvalidStatusTransition):
        superseded.disable(MemoryStatus.ARCHIVED, now)
    with pytest.raises(InvalidStatusTransition):
        superseded.disable(MemoryStatus.ACTIVE, now)


async def test_queue_admin_does_not_requeue_migrated_provenance():
    from test_extraction_worker import TENANT_ID, pending_job

    from agent_memory.infrastructure.in_memory_queue_admin import InMemoryQueueAdmin

    job = replace(pending_job(), status=JobStatus.DEAD, last_error_code="EXTRACTOR_MIGRATED")
    jobs = {job.job_id: job}
    admin = InMemoryQueueAdmin(jobs, TENANT_ID)
    assert await admin.requeue(job_type="extract_event", limit=100) == 0
    assert jobs[job.job_id].status == JobStatus.DEAD


async def test_model_rebuild_memory_adapter_is_tenant_scoped():
    from agent_memory.infrastructure.in_memory_queue_admin import InMemoryQueueAdmin

    tenant, foreign, version, other_version = (uuid4() for _ in range(4))
    jobs = {}
    admin = InMemoryQueueAdmin(
        jobs, tenant, embeddings={(tenant, version): "old", (foreign, other_version): "old"}
    )
    assert await admin.rebuild_model("old", "operation") == 1
    assert await admin.rebuild_model("old", "operation") == 0
    assert all(
        j.tenant_id == tenant and j.payload["version_id"] == str(version) for j in jobs.values()
    )


@pytest.mark.parametrize("status", ["archived", "superseded", "invalidated", "active"])
async def test_delete_permission_does_not_grant_other_lifecycle_actions(status):
    from test_explicit_memory import make_service, principal, workspace_command

    from agent_memory.application.commands import DisableMemoryCommand
    from agent_memory.domain.enums import MemoryStatus
    from agent_memory.domain.errors import MemoryScopeForbidden

    service, _, _ = make_service()
    who = principal()
    created = await service.remember(workspace_command(), who)
    with pytest.raises(MemoryScopeForbidden):
        await service.disable(DisableMemoryCommand(created.memory_id, 1, MemoryStatus(status)), who)


async def test_cached_vector_returns_while_all_provider_slots_are_busy():
    cache = QueryVectors(
        Settings(
            embedding_model="m",
            embedding_endpoint="https://test.invalid/e",
            query_embedding_concurrency=1,
            query_embedding_timeout_seconds=0.1,
        )
    )
    cache._client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"data": [{"embedding": [1.0] * 1024}]})
        )
    )
    tenant = uuid4()
    try:
        await cache.embed(tenant, "warm")
        await cache._slots.acquire()
        try:
            assert (await asyncio.wait_for(cache.embed(tenant, "warm"), 0.05))[1] == "cache"
        finally:
            cache._slots.release()
    finally:
        await cache.aclose()
