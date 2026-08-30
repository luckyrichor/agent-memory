# Event and Asynchronous Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a tenant-isolated Event → Transactional Outbox → PostgreSQL Job Queue → leased Worker pipeline that deterministically turns one Coding Agent build-failure event into one Candidate Memory with Evidence.

**Architecture:** Keep the modular monolith and existing PostgreSQL transaction boundary. The authenticated API writes immutable Events and Outbox rows atomically; a tenant-scoped dispatcher creates idempotent Jobs; a leased Worker loads the Event, calls a replaceable extractor, and atomically writes Candidate Memory, MemoryVersion, Evidence, and Job success.

**Tech Stack:** Python 3.12, uv project virtual environment, FastAPI, Pydantic v2, SQLAlchemy 2 async, psycopg 3, Alembic, PostgreSQL 16 + pgvector in Docker, pytest, pytest-asyncio, Testcontainers, Ruff, mypy.

**Spec:** `docs/superpowers/specs/2026-08-30-event-async-extraction-design.md`

## Global Constraints

- Python remains `>=3.12,<3.13`; never install project packages with system `pip`.
- Use only `uv sync --dev`, `uv add`, `uv add --dev`, and `uv run`; dependencies live in the project `.venv`.
- This plan adds no Python dependency; do not add Redis, Kafka, RabbitMQ, Elasticsearch, or a native macOS PostgreSQL install.
- PostgreSQL/pgvector runs only through Docker or Testcontainers.
- Every production behavior follows RED → GREEN → REFACTOR; observe the intended test failure before implementation.
- Tenant comes only from `RequestPrincipal`; request bodies and queue payloads cannot override it.
- Every new PostgreSQL table uses tenant-inclusive keys, forced RLS, and the non-bypass application role.
- Event and Outbox commit atomically; Candidate, MemoryVersion, Evidence, and Job success commit atomically.
- Logs and evaluator output contain stable IDs and reason codes, never Event payload or Memory content.

---

## File map

| File | Responsibility |
|---|---|
| `src/agent_memory/domain/events.py` | Immutable Event, scope-preserving candidate, event/job enums and validation |
| `src/agent_memory/domain/jobs.py` | Job state and lease transition rules |
| `src/agent_memory/application/event_commands.py` | Batch ingestion commands and results |
| `src/agent_memory/application/event_ports.py` | Event/Outbox/Job/Extraction transaction protocols |
| `src/agent_memory/application/event_ingestion.py` | Permission, hashing, batch and idempotency orchestration |
| `src/agent_memory/application/outbox_dispatcher.py` | Tenant-scoped Outbox-to-Job dispatch |
| `src/agent_memory/application/extraction.py` | `MemoryExtractor` and Coding failure rule extractor |
| `src/agent_memory/application/extraction_worker.py` | Lease-aware extraction orchestration and retry decisions |
| `src/agent_memory/infrastructure/in_memory_events.py` | Fast unit-test adapters |
| `src/agent_memory/infrastructure/event_repositories.py` | PostgreSQL Event ingestion, Outbox, Job and extraction transaction adapters |
| `src/agent_memory/api/event_schemas.py` | Strict batch request and response schemas |
| `src/agent_memory/api/event_routes.py` | `POST /v1/events:batch` |
| `src/agent_memory/workers/extraction.py` | Tenant-scoped dispatcher/worker CLI |
| `migrations/versions/0003_event_pipeline.py` | Event, Outbox, Job and Evidence schema plus RLS |
| `tests/unit/domain/test_events.py` | Event/scope/hash/domain invariants |
| `tests/unit/domain/test_jobs.py` | Job lease and retry state machine |
| `tests/unit/application/test_event_ingestion.py` | Ingestion idempotency, conflicts and authorization |
| `tests/unit/application/test_extraction.py` | Rule extractor and worker decisions |
| `tests/integration/test_event_pipeline_schema.py` | Migration constraints and RLS |
| `tests/integration/test_event_pipeline.py` | Atomic ingestion, dispatch, claim and extraction |
| `tests/api/test_event_api.py` | Authentication and strict batch API |
| `tests/e2e/test_automatic_memory_pipeline.py` | Duplicate build-failure Event yields exactly one complete lineage |

---

### Task 1: Event and Job domain contracts

**Files:**
- Create: `src/agent_memory/domain/events.py`
- Create: `src/agent_memory/domain/jobs.py`
- Modify: `src/agent_memory/domain/errors.py`
- Test: `tests/unit/domain/test_events.py`
- Test: `tests/unit/domain/test_jobs.py`

**Interfaces:**
- Produces: `EventType`, `Event`, `EventDraft`, `MemoryCandidate`, `JobStatus`, `Job`, `InvalidEvent`, `EventIdempotencyConflict`, `EventSequenceConflict`, `LeaseLost`.
- `EventDraft.request_hash()` is the canonical hash used by every repository.
- `MemoryCandidate.scope` is copied from the Event and cannot be widened by the extractor.

- [ ] **Step 1: Write failing Event tests**

```python
def test_event_hash_is_stable_across_payload_key_order() -> None:
    first = event_draft(payload={"exit_code": 1, "tool_name": "build"})
    second = event_draft(payload={"tool_name": "build", "exit_code": 1})
    assert first.request_hash() == second.request_hash()


def test_event_rejects_non_positive_sequence_and_invalid_scope() -> None:
    with pytest.raises(InvalidEvent, match="sequence_number"):
        event_draft(sequence_number=0)
    with pytest.raises(InvalidScope):
        event_draft(scope=MemoryScope(ScopeKind.WORKSPACE, None, None))
```

- [ ] **Step 2: Run Event tests RED**

Run: `uv run pytest tests/unit/domain/test_events.py -v`

Expected: collection fails because `agent_memory.domain.events` does not exist.

- [ ] **Step 3: Implement immutable Event contracts**

Use frozen slotted dataclasses. `EventDraft.request_hash()` serializes exactly these normalized fields with sorted JSON keys: idempotency key, session, sequence, type, agent, occurred time in UTC ISO-8601, scope kind/workspace/user, and payload. Reject sequence `< 1`, blank identifiers, naive occurred times, unknown Event type, payloads over 65,536 UTF-8 JSON bytes, and payload nesting deeper than four containers.

```python
class EventType(str, Enum):
    TOOL_RESULT = "tool.result"
    TASK_COMPLETED = "task.completed"
    USER_CONFIRMED = "user.confirmed"


@dataclass(frozen=True, slots=True)
class Event:
    tenant_id: UUID
    event_id: UUID
    draft: EventDraft
    actor_user_id: UUID
    received_at: datetime
```

- [ ] **Step 4: Write and run Job state tests RED then GREEN**

Cover claim from pending, refusal before an active lease expires, reclaim after expiry, renewal by the same owner, renewal rejection for a different owner, deterministic backoff `min(2 ** attempts, 300)`, success, retry_wait, and dead at `max_attempts`.

Run: `uv run pytest tests/unit/domain/test_events.py tests/unit/domain/test_jobs.py -v`

Expected: all pass after implementing `Job.claim`, `Job.renew`, `Job.succeed`, and `Job.fail` as immutable transitions.

- [ ] **Step 5: Run quality checks and commit**

```bash
uv run ruff check src tests
uv run mypy src
git add src/agent_memory/domain tests/unit/domain
git commit -m "feat: define event and leased job domains"
```

---

### Task 2: Batch Event ingestion application service

**Files:**
- Create: `src/agent_memory/application/event_commands.py`
- Create: `src/agent_memory/application/event_ports.py`
- Create: `src/agent_memory/application/event_ingestion.py`
- Create: `src/agent_memory/infrastructure/in_memory_events.py`
- Test: `tests/unit/application/test_event_ingestion.py`

**Interfaces:**
- Consumes: `EventDraft`, `RequestPrincipal`, `MemoryScope`.
- Produces: `IngestEventBatchCommand`, `EventIngestionResult`, `EventIngestionService.ingest_batch` and `EventIngestionRepository.ingest_batch`.
- Repository accepts the complete validated batch once, so implementations can guarantee all-or-nothing Event + Outbox writes.

- [ ] **Step 1: Write failing authorization and idempotency tests**

```python
@pytest.mark.asyncio
async def test_batch_replay_returns_original_ids_without_new_outbox() -> None:
    service, repository = make_ingestion_service()
    first = await service.ingest_batch(batch_command(), principal())
    replay = await service.ingest_batch(batch_command(), principal())
    assert replay[0].event_id == first[0].event_id
    assert replay[0].disposition == "duplicate"
    assert repository.event_count == 1
    assert repository.outbox_count == 1


@pytest.mark.asyncio
async def test_workspace_scope_requires_access_and_rolls_back_whole_batch() -> None:
    service, repository = make_ingestion_service()
    with pytest.raises(MemoryScopeForbidden):
        await service.ingest_batch(mixed_authorized_batch(), project_b_principal())
    assert repository.event_count == 0
```

- [ ] **Step 2: Run ingestion tests RED**

Run: `uv run pytest tests/unit/application/test_event_ingestion.py -v`

Expected: imports fail because ingestion modules are absent.

- [ ] **Step 3: Implement commands, ports and service GREEN**

`EventIngestionService` rejects empty batches and batches over 100, requires `memory:write`, checks Workspace and subject-user access with the same rules as `ExplicitMemoryService`, generates server-side Event and Outbox UUIDs, and delegates one atomic call.

```python
class EventIngestionRepository(Protocol):
    async def ingest_batch(
        self,
        tenant_id: UUID,
        actor_user_id: UUID,
        drafts: tuple[EventDraft, ...],
    ) -> tuple[EventIngestionResult, ...]:
        raise NotImplementedError
```

The in-memory adapter preflights every idempotency and sequence conflict before mutating dictionaries; it appends one `event.recorded` Outbox record only for newly accepted Events.

- [ ] **Step 4: Add conflict and atomicity cases**

Test identical replay, same idempotency key with changed payload, same Session sequence with another key, duplicate items inside one batch, unauthorized user scope, and a valid 100-item batch. Verify conflict reason codes and zero partial writes.

Run: `uv run pytest tests/unit/application/test_event_ingestion.py -v`

Expected: all pass.

- [ ] **Step 5: Run regression and commit**

```bash
uv run pytest tests/unit -v
uv run ruff check src tests
uv run mypy src
git add src/agent_memory/application src/agent_memory/infrastructure/in_memory_events.py tests/unit/application
git commit -m "feat: ingest idempotent event batches"
```

---

### Task 3: PostgreSQL Event pipeline schema and tenant RLS

**Files:**
- Create: `migrations/versions/0003_event_pipeline.py`
- Modify: `src/agent_memory/infrastructure/orm.py`
- Test: `tests/integration/test_event_pipeline_schema.py`
- Modify: `tests/integration/test_tenant_isolation.py`

**Interfaces:**
- Produces: `EventRow`, `OutboxMessageRow`, `JobRow`, `EvidenceRow` matching the approved design exactly.
- Migration revision: `0003_event_pipeline`; down revision: `0002_current_version_integrity`.

- [ ] **Step 1: Write failing migration structure test**

Assert all four tables, tenant-inclusive primary/foreign/unique constraints, status checks, Event scope check, indexes for pending Outbox and claimable Jobs, and `events.payload` JSONB.

Run: `uv run pytest tests/integration/test_event_pipeline_schema.py::test_event_pipeline_schema -v`

Expected: FAIL because migration `0003_event_pipeline` and tables do not exist.

- [ ] **Step 2: Implement migration and ORM GREEN**

Create:

- `events` with unique `(tenant_id,idempotency_key)` and `(tenant_id,session_id,sequence_number)`.
- `outbox_messages` with unique `(tenant_id,topic,aggregate_id)`.
- `jobs` with unique `(tenant_id,job_type,idempotency_key)`.
- `evidence` with composite FKs to `memory_versions` and `events`.

Enable and force RLS on every table, create `USING` plus `WITH CHECK` policies using `app.current_tenant_id`, and grant CRUD to `agent_memory_app`.

- [ ] **Step 3: Test migration round trip**

Run upgrade to head, assert objects, downgrade to `0002_current_version_integrity`, assert all four removed, then upgrade to head again.

Run: `uv run pytest tests/integration/test_event_pipeline_schema.py -v`

Expected: all pass.

- [ ] **Step 4: Extend known-ID cross-tenant attack test**

Tenant A inserts Event, Outbox, Job and Evidence. Under the non-superuser Tenant B session assert no select/update/delete visibility and assert forged cross-tenant Event/Evidence foreign keys fail. Re-read under Tenant A and verify unchanged rows.

Run: `uv run pytest tests/integration/test_tenant_isolation.py -v`

Expected: all attacks are blocked.

- [ ] **Step 5: Verify and commit**

```bash
uv run pytest tests/integration/test_event_pipeline_schema.py tests/integration/test_tenant_isolation.py -v
uv run ruff check src tests migrations
uv run mypy src
git add migrations/versions/0003_event_pipeline.py src/agent_memory/infrastructure/orm.py tests/integration
git commit -m "feat: add tenant-isolated event pipeline schema"
```

---

### Task 4: PostgreSQL ingestion repository and authenticated Event API

**Files:**
- Create: `src/agent_memory/infrastructure/event_repositories.py`
- Create: `src/agent_memory/api/event_schemas.py`
- Create: `src/agent_memory/api/event_routes.py`
- Modify: `src/agent_memory/api/app.py`
- Test: `tests/integration/test_event_pipeline.py`
- Test: `tests/api/test_event_api.py`

**Interfaces:**
- Consumes: `EventIngestionRepository`, existing `JwtPrincipalResolver`, principal-scoped async session.
- Produces: `PostgresEventIngestionRepository` and `POST /v1/events:batch`.

- [ ] **Step 1: Write PostgreSQL atomic ingestion tests RED**

Use the real non-bypass app role. Assert one Event and one pending Outbox commit together, identical replay returns the original Event, changed replay raises `EventIdempotencyConflict`, sequence collision raises `EventSequenceConflict`, and a later conflicting batch item leaves no earlier batch rows.

Run: `uv run pytest tests/integration/test_event_pipeline.py -k ingestion -v`

Expected: FAIL because PostgreSQL ingestion adapter is absent.

- [ ] **Step 2: Implement PostgreSQL ingestion GREEN**

Preflight existing idempotency keys and sequence positions in the tenant-scoped transaction. Lock conflicting rows where present. Build all new `EventRow` and `OutboxMessageRow` objects only after preflight succeeds; flush once. Translate unique-constraint races into stable domain conflicts without returning database error text.

Run: `uv run pytest tests/integration/test_event_pipeline.py -k ingestion -v`

Expected: all ingestion cases pass.

- [ ] **Step 3: Write Event API tests RED**

Cover missing JWT 401, body `tenant_id` 422, empty/101-item batch 422, wrong Workspace 403, valid batch 202, duplicate disposition with same Event ID, changed idempotent payload 409 and stable error code.

Run: `uv run pytest tests/api/test_event_api.py -v`

Expected: 404 or import failure because route and schemas are absent.

- [ ] **Step 4: Implement strict schemas and route GREEN**

Use `ConfigDict(extra="forbid")` on every request model. Model `tool.result` payload as a discriminated strict schema with only `tool_name`, `exit_code`, `summary`, `error_code`. Convert schema to `EventDraft` after authentication, bind Principal in `create_app`, and map domain conflicts to 409 envelopes.

Run: `uv run pytest tests/api/test_event_api.py tests/api/test_memory_api.py -v`

Expected: all API tests pass without regressing Memory routes.

- [ ] **Step 5: Full check and commit**

```bash
uv run pytest tests/unit tests/integration tests/api -v
uv run ruff check src tests migrations
uv run mypy src
git add src/agent_memory/api src/agent_memory/infrastructure/event_repositories.py tests/api tests/integration/test_event_pipeline.py
git commit -m "feat: expose atomic event ingestion API"
```

---

### Task 5: Outbox dispatcher and leased PostgreSQL Job Queue

**Files:**
- Create: `src/agent_memory/application/outbox_dispatcher.py`
- Extend: `src/agent_memory/application/event_ports.py`
- Extend: `src/agent_memory/infrastructure/in_memory_events.py`
- Extend: `src/agent_memory/infrastructure/event_repositories.py`
- Test: `tests/unit/application/test_outbox_dispatcher.py`
- Test: `tests/integration/test_event_pipeline.py`

**Interfaces:**
- Produces: `OutboxRepository.dispatch_once(tenant_id, batch_size, extractor_version)`, `JobQueue.claim`, `renew`, `succeed`, and `fail`.
- Job natural key: `extract_event:{event_id}:{extractor_version}`.

- [ ] **Step 1: Write dispatcher idempotency test RED**

```python
@pytest.mark.asyncio
async def test_replayed_dispatch_creates_one_job_and_publishes_outbox() -> None:
    dispatcher, store = seeded_dispatcher()
    assert await dispatcher.dispatch_once(TENANT_A, 10) == 1
    assert await dispatcher.dispatch_once(TENANT_A, 10) == 0
    assert store.job_count == 1
    assert store.outbox_status == "published"
```

Run: `uv run pytest tests/unit/application/test_outbox_dispatcher.py -v`

Expected: import failure.

- [ ] **Step 2: Implement dispatcher and in-memory queue GREEN**

Dispatcher validates `1 <= batch_size <= 100`, uses configured extractor version, and delegates tenant-scoped atomic dispatch. Duplicate Job keys count as successfully published, not as new Jobs.

- [ ] **Step 3: Write PostgreSQL concurrency and lease tests RED**

Run two async dispatch calls and assert one Job. Seed two Jobs, claim concurrently from two workers, assert distinct IDs. Verify active lease cannot be stolen, expired lease can be reclaimed, wrong owner cannot renew/succeed/fail, and `max_attempts` transitions to dead.

Run: `uv run pytest tests/integration/test_event_pipeline.py -k 'dispatch or claim or lease' -v`

Expected: failure because SQL claim/update methods are absent.

- [ ] **Step 4: Implement PostgreSQL queue GREEN**

Use a CTE or locked select with `FOR UPDATE SKIP LOCKED`, ordered by `available_at, created_at, job_id`. Claim eligible pending/retry_wait or expired running Jobs. State updates include tenant, Job ID, owner and current lease predicates; return `LeaseLost` when rowcount is zero.

Run: `uv run pytest tests/unit/application/test_outbox_dispatcher.py tests/integration/test_event_pipeline.py -v`

Expected: all queue tests pass.

- [ ] **Step 5: Verify and commit**

```bash
uv run pytest tests/unit tests/integration -v
uv run ruff check src tests migrations
uv run mypy src
git add src/agent_memory/application src/agent_memory/infrastructure tests/unit/application tests/integration/test_event_pipeline.py
git commit -m "feat: dispatch outbox jobs with recoverable leases"
```

---

### Task 6: Replaceable extractor and scope-safe candidates

**Files:**
- Create: `src/agent_memory/application/extraction.py`
- Modify: `src/agent_memory/domain/models.py`
- Test: `tests/unit/application/test_extraction.py`
- Test: `tests/unit/domain/test_memory.py`

**Interfaces:**
- Produces: `MemoryExtractor` protocol, `CodingFailureRuleExtractor`, `MemoryCandidate` validation and a Memory factory that accepts explicit status/trust fields while preserving Explicit Memory defaults.

- [ ] **Step 1: Write rule extractor tests RED**

```python
@pytest.mark.asyncio
async def test_failed_build_creates_scope_preserving_episodic_candidate() -> None:
    event = build_event(exit_code=1, summary="  x86 dependency failed on arm64  ")
    candidates = await CodingFailureRuleExtractor().extract(event)
    assert len(candidates) == 1
    assert candidates[0].content == "x86 dependency failed on arm64"
    assert candidates[0].scope == event.draft.scope
    assert candidates[0].memory_type is MemoryType.EPISODIC
```

Also assert zero candidates for success, unsupported tool, empty summary and non-tool Event.

- [ ] **Step 2: Run extractor tests RED**

Run: `uv run pytest tests/unit/application/test_extraction.py -v`

Expected: import failure.

- [ ] **Step 3: Implement protocol and deterministic extractor GREEN**

`MemoryExtractor.version` is a stable property. `CodingFailureRuleExtractor.version` is exactly `coding-failure-rule-v1`; it has no database or network dependency and returns immutable candidates.

- [ ] **Step 4: Extend Memory factory through TDD**

Add a failing domain test proving candidate creation uses `MemoryStatus.CANDIDATE`, `AuthorityLevel.TOOL_VERIFIED`, `VerificationStatus.VERIFIED`, confidence `1.0`, utility `0.5`, while existing `Memory.create` calls still default to explicit user-confirmed active memory.

Run: `uv run pytest tests/unit/application/test_extraction.py tests/unit/domain/test_memory.py -v`

Expected: all pass after a focused factory extension; do not duplicate Memory construction in the Worker.

- [ ] **Step 5: Verify and commit**

```bash
uv run pytest tests/unit -v
uv run ruff check src tests
uv run mypy src
git add src/agent_memory/application/extraction.py src/agent_memory/domain tests/unit
git commit -m "feat: extract scope-safe coding failure candidates"
```

---

### Task 7: Extraction Worker and atomic Candidate lineage

**Files:**
- Create: `src/agent_memory/application/extraction_worker.py`
- Extend: `src/agent_memory/application/event_ports.py`
- Extend: `src/agent_memory/infrastructure/in_memory_events.py`
- Extend: `src/agent_memory/infrastructure/event_repositories.py`
- Test: `tests/unit/application/test_extraction_worker.py`
- Test: `tests/integration/test_event_pipeline.py`
- Create: `tests/e2e/test_automatic_memory_pipeline.py`

**Interfaces:**
- Produces: `ExtractionWorker.run_once(tenant_id: UUID, worker_id: str) -> WorkerResult` and `ExtractionTransaction.commit_candidates(tenant_id: UUID, job_id: UUID, worker_id: str, event: Event, candidates: tuple[MemoryCandidate, ...], now: datetime) -> None`.
- `WorkerResult` contains only Job ID, outcome and reason code; no Event content.

- [ ] **Step 1: Write Worker unit tests RED**

Test no available Job, successful no-candidate Event, successful candidate, extractor transient failure → retry_wait, permanent validation failure → dead, and lease lost before commit → no candidate plus `LEASE_LOST`.

Run: `uv run pytest tests/unit/application/test_extraction_worker.py -v`

Expected: import failure.

- [ ] **Step 2: Implement orchestration GREEN**

Worker claims one tenant Job, loads the referenced Event under the same Tenant, calls the extractor, rejects any candidate whose Scope differs from the Event, and delegates one atomic commit. It reports stable reason codes and never interpolates exception strings into `WorkerResult`.

- [ ] **Step 3: Write PostgreSQL atomicity tests RED**

Inject failure immediately before Evidence insert and assert Candidate Memory/Version and Job success all roll back. Run the normal path and assert one Candidate, one Version, one `triggered_by` Evidence and succeeded Job. Replay processing and assert counts stay one.

Run: `uv run pytest tests/integration/test_event_pipeline.py -k extraction -v`

Expected: failure because extraction transaction adapter is absent.

- [ ] **Step 4: Implement extraction transaction and end-to-end GREEN**

Validate current lease using tenant, Job ID, worker ID and `leased_until > now`. Add Memory and Version using existing repository semantics, flush to satisfy deferred FKs, insert Evidence, and mark Job succeeded in the same session transaction. The end-to-end test ingests the same build Event twice, dispatches twice, runs Worker twice and asserts all six lineage counts are exactly one.

Run: `uv run pytest tests/unit/application/test_extraction_worker.py tests/integration/test_event_pipeline.py tests/e2e/test_automatic_memory_pipeline.py -v`

Expected: all pass.

- [ ] **Step 5: Full regression and commit**

```bash
uv run pytest -v
uv run ruff check src tests migrations
uv run mypy src
git add src/agent_memory/application src/agent_memory/infrastructure tests/unit/application tests/integration tests/e2e
git commit -m "feat: persist extracted candidates with event lineage"
```

---

### Task 8: Worker CLI, evaluation, documentation and release gate

**Files:**
- Create: `src/agent_memory/workers/__init__.py`
- Create: `src/agent_memory/workers/extraction.py`
- Create: `tests/unit/workers/test_extraction_cli.py`
- Modify: `src/agent_memory/evals/foundation_runner.py`
- Modify: `tests/unit/evals/test_foundation_runner.py`
- Modify: `README.md`

**Interfaces:**
- Produces CLI commands:
  - `uv run python -m agent_memory.workers.extraction dispatch --tenant-id <uuid> --once`
  - `uv run python -m agent_memory.workers.extraction work --tenant-id <uuid> --worker-id <id> --once`
  - Without `--once`, loop with a configurable 1–60 second poll interval and graceful SIGINT/SIGTERM shutdown.

- [ ] **Step 1: Write CLI and safe-output tests RED**

Assert missing Tenant is a parser error, poll interval outside 1–60 is rejected, `--once` exits zero after one call, and failure output includes Job ID/reason code but not seeded Event summary.

Run: `uv run pytest tests/unit/workers/test_extraction_cli.py -v`

Expected: import failure.

- [ ] **Step 2: Implement CLI GREEN**

Build `Settings` from `MEMORY_*`, create tenant-scoped sessions with an internal system Principal that has only required queue permissions, instantiate `CodingFailureRuleExtractor`, and dispose the engine on exit. Use `asyncio.Event` for signal-aware looping; use `asyncio.sleep`, never blocking `time.sleep`.

- [ ] **Step 3: Extend evaluator RED then GREEN**

Add `automatic_memory_pipeline` to the safe evaluator summary. It must assert one Event, Outbox, Job, Candidate, Version and Evidence after replay while printing only case IDs, reason codes and counters. Update expected total from 7 to 8.

Run: `uv run pytest tests/unit/evals/test_foundation_runner.py -v`

Expected: fail at total 7 before implementation, then pass at total 8.

- [ ] **Step 4: Update README**

Add the exact strict Event batch curl, explain immutable Event versus Audit, show dispatcher and Worker one-shot/continuous commands, document lease/retry/dead semantics, state that no new Python dependency was added, and preserve the Docker-only PostgreSQL instruction.

- [ ] **Step 5: Run complete release gate**

```bash
uv sync --dev
uv run pytest -v
uv run ruff check src tests migrations
uv run mypy src
uv run python -m agent_memory.evals.foundation_runner
git diff --check
```

Expected evaluator line:

```text
Foundation evaluator: total=8 passed=8 failed=0 tenant_leaks=0 deleted_memory_hits=0
```

- [ ] **Step 6: Commit**

```bash
git add README.md src/agent_memory/workers src/agent_memory/evals tests/unit/workers tests/unit/evals
git commit -m "docs: verify automatic event extraction workflow"
```

## Final verification

After Task 8, verify branch history contains eight reviewable implementation commits, the worktree is clean, and no dependency was installed outside `.venv`. Compare `uv.lock` with the base; because no package is added, it should remain unchanged.
