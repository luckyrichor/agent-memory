# Memory Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first independently usable slice of the enterprise Agent memory platform: executable evaluation fixtures, domain aggregates, PostgreSQL persistence, tenant isolation, explicit memory creation/correction, immediate retrieval disablement, and audited HTTP APIs.

**Architecture:** Implement a Python modular monolith with ports around storage and identity. The application service is shared by FastAPI remote mode and a future embedded adapter; PostgreSQL is the enterprise source of truth, while unit tests use an in-memory repository. This plan intentionally excludes event extraction, embeddings, hybrid retrieval, workers, and physical deletion propagation; each will receive a separate implementation plan after this foundation passes its acceptance gates.

**Tech Stack:** Python 3.12 managed by uv, FastAPI, Pydantic 2, SQLAlchemy 2 async, psycopg 3, Alembic, PostgreSQL 16 with pgvector, PyJWT with cryptography, pytest, pytest-asyncio, httpx, and testcontainers.

**Spec:** `docs/superpowers/specs/2026-08-30-enterprise-agent-memory-system-design.md`

## Global Constraints

- Run project commands through `uv run`; do not modify macOS system Python 3.9.6.
- Use PostgreSQL 16 plus pgvector in Docker for integration tests; a local `psql` installation is not required.
- Every persisted domain table includes `tenant_id`; cross-tenant foreign keys and reads are forbidden.
- The authenticated principal supplies `tenant_id` and `user_id`; request bodies never choose the tenant.
- Memory content changes create immutable `MemoryVersion` rows and increment `Memory.revision`; never overwrite version content.
- Explicit writes require an idempotency key.
- Deleted, invalidated, superseded, and archived memories are excluded from normal reads immediately.
- Domain and application packages must not import FastAPI or SQLAlchemy.
- Write each behavior test first, run it red, implement the minimum behavior, then run it green.
- Keep `.DS_Store` untracked and out of every commit.

---

## File Map

```text
pyproject.toml                         Project metadata, dependencies, pytest/ruff/mypy settings
.python-version                       Python 3.12 selection for uv
compose.yaml                          Local PostgreSQL 16 + pgvector service
alembic.ini                           Migration runner configuration
src/agent_memory/
├── __init__.py
├── config.py                         Environment-backed application settings
├── domain/
│   ├── enums.py                      Memory, status, scope, authority enums
│   ├── errors.py                     Domain and application error types
│   ├── models.py                     Scope, Memory, MemoryVersion aggregates
│   └── principal.py                  Authenticated RequestPrincipal
├── application/
│   ├── commands.py                   Typed command and result records
│   ├── ports.py                      Repository, audit, idempotency interfaces
│   └── explicit_memory.py            Explicit create/correct/delete use cases
├── infrastructure/
│   ├── db.py                         Async engine/session and tenant context
│   ├── orm.py                        SQLAlchemy mappings
│   ├── repositories.py               PostgreSQL repository implementations
│   └── in_memory.py                  Deterministic unit-test adapters
├── api/
│   ├── auth.py                       RS256 JWT validation and principal creation
│   ├── errors.py                     Stable HTTP error envelope
│   ├── schemas.py                    Pydantic request/response contracts
│   ├── routes.py                     Memory HTTP endpoints
│   └── app.py                        FastAPI composition root
└── evals/
    ├── schema.py                     Golden case schema
    └── foundation_runner.py          Foundation acceptance evaluator
migrations/
├── env.py                            Async Alembic environment
└── versions/0001_memory_foundation.py
tests/
├── fixtures/golden/foundation.jsonl  Executable first-use-case expectations
├── unit/domain/test_memory.py
├── unit/application/test_explicit_memory.py
├── unit/evals/test_foundation_runner.py
├── integration/conftest.py
├── integration/test_postgres_repository.py
├── integration/test_tenant_isolation.py
└── api/test_memory_api.py
README.md                              Setup, commands, API examples, scope boundaries
```

## Task 1: Project bootstrap and executable foundation cases

**Files:**
- Create: `.python-version`
- Create: `pyproject.toml`
- Create: `src/agent_memory/__init__.py`
- Create: `src/agent_memory/evals/schema.py`
- Create: `src/agent_memory/evals/foundation_runner.py`
- Create: `tests/fixtures/golden/foundation.jsonl`
- Create: `tests/unit/evals/test_foundation_runner.py`

**Interfaces:**
- Consumes: none.
- Produces: `FoundationCase`, `FoundationActual`, and `evaluate_foundation_case(case, actual) -> FoundationScore`.

- [ ] **Step 1: Create the Python project configuration**

Create `.python-version` containing:

```text
3.12
```

Create `pyproject.toml` with package name `agent-memory`, source layout `src`, and these dependency groups:

```toml
[project]
name = "agent-memory"
version = "0.1.0"
requires-python = ">=3.12,<3.13"
dependencies = [
  "alembic>=1.13,<2",
  "fastapi>=0.115,<1",
  "pgvector>=0.3,<1",
  "psycopg[binary,pool]>=3.2,<4",
  "pydantic>=2.9,<3",
  "pydantic-settings>=2.5,<3",
  "pyjwt[crypto]>=2.9,<3",
  "sqlalchemy[asyncio]>=2.0.35,<3",
  "uvicorn>=0.30,<1",
]

[dependency-groups]
dev = [
  "httpx>=0.27,<1",
  "mypy>=1.11,<2",
  "pytest>=8.3,<9",
  "pytest-asyncio>=0.24,<1",
  "ruff>=0.6,<1",
  "testcontainers[postgres]>=4.8,<5",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/agent_memory"]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.mypy]
python_version = "3.12"
strict = true
packages = ["agent_memory"]
```

- [ ] **Step 2: Write the failing evaluator test**

Create a test that loads one JSONL case and asserts that an exact actual result receives full credit while a cross-tenant result raises `ValueError`:

```python
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
            actual.model_copy(update={"tenant_id": "tenant-b"}),
        )
```

- [ ] **Step 3: Run the test and verify it fails**

Run:

```bash
uv sync --dev
uv run pytest tests/unit/evals/test_foundation_runner.py -v
```

Expected: collection fails because `agent_memory.evals.schema` does not exist.

- [ ] **Step 4: Implement the fixture schema and evaluator**

Define strict Pydantic models. `FoundationScore` contains `passed: bool` and `reasons: tuple[str, ...]`. The evaluator raises `ValueError("tenant mismatch")` before scoring when Tenant differs, and otherwise checks type, scope, content, and active status.

The first JSONL case represents the arm64/x86_64 build failure and uses `tenant-a`, `project-a`, `episodic`, `workspace`, and the verified resolution text from the design spec.

- [ ] **Step 5: Run verification**

Run:

```bash
uv run pytest tests/unit/evals/test_foundation_runner.py -v
uv run ruff check src tests
uv run mypy src
```

Expected: all commands exit 0.

- [ ] **Step 6: Commit**

```bash
git add .python-version pyproject.toml src/agent_memory tests/fixtures tests/unit/evals
git commit -m "test: define memory foundation acceptance cases"
```

## Task 2: Domain aggregate, Scope validation, and immutable versions

**Files:**
- Create: `src/agent_memory/domain/enums.py`
- Create: `src/agent_memory/domain/errors.py`
- Create: `src/agent_memory/domain/models.py`
- Create: `src/agent_memory/domain/principal.py`
- Create: `tests/unit/domain/test_memory.py`

**Interfaces:**
- Consumes: standard `UUID`, timezone-aware `datetime`.
- Produces: `MemoryScope.validate()`, `Memory.create(...)`, `Memory.add_version(...)`, `Memory.disable(status, now)`, and `RequestPrincipal.can_access_workspace(...)`.

- [ ] **Step 1: Write Scope matrix tests**

Cover all four valid combinations and these invalid combinations:

```python
@pytest.mark.parametrize(
    ("kind", "workspace_id", "subject_user_id"),
    [
        (ScopeKind.TENANT, "project-a", None),
        (ScopeKind.WORKSPACE, None, None),
        (ScopeKind.USER_GLOBAL, None, None),
        (ScopeKind.USER_WORKSPACE, "project-a", None),
    ],
)
def test_invalid_scope_combinations_are_rejected(kind, workspace_id, subject_user_id):
    with pytest.raises(InvalidScope):
        MemoryScope(kind, workspace_id, subject_user_id)
```

- [ ] **Step 2: Write version immutability and revision tests**

Assert that `Memory.create` creates revision 1 and version 1, `add_version(expected_revision=1)` returns a new aggregate with revision 2, and the original version object remains unchanged. Assert stale expected revision raises `RevisionConflict`.

- [ ] **Step 3: Run domain tests red**

Run:

```bash
uv run pytest tests/unit/domain/test_memory.py -v
```

Expected: FAIL because domain types are missing.

- [ ] **Step 4: Implement focused domain types**

Use frozen dataclasses for `MemoryScope` and `MemoryVersion`. Use a non-mutable aggregate method style in which `add_version` returns a replaced `Memory` and new `MemoryVersion`. Enums contain exactly the types and statuses in the design spec.

`Memory.disable` accepts only `SUPERSEDED`, `INVALIDATED`, `ARCHIVED`, or `DELETED`, records the matching timestamp, and rejects transitions from `DELETED`.

`RequestPrincipal` contains `tenant_id`, `user_id`, `roles`, `permissions`, and `allowed_workspace_ids`; `can_access_workspace(None)` is allowed only for Tenant/User-global operations permitted by Policy, not as an authorization shortcut.

- [ ] **Step 5: Run domain verification**

```bash
uv run pytest tests/unit/domain/test_memory.py -v
uv run ruff check src/agent_memory/domain tests/unit/domain
uv run mypy src/agent_memory/domain
```

Expected: all commands exit 0.

- [ ] **Step 6: Commit**

```bash
git add src/agent_memory/domain tests/unit/domain
git commit -m "feat: add scoped versioned memory domain"
```

## Task 3: Application ports and explicit memory use cases

**Files:**
- Create: `src/agent_memory/application/commands.py`
- Create: `src/agent_memory/application/ports.py`
- Create: `src/agent_memory/application/explicit_memory.py`
- Create: `src/agent_memory/infrastructure/in_memory.py`
- Create: `tests/unit/application/test_explicit_memory.py`

**Interfaces:**
- Consumes: Task 2 `Memory`, `MemoryScope`, `MemoryVersion`, `RequestPrincipal`.
- Produces: `ExplicitMemoryService.remember`, `get`, `correct`, and `disable`; `MemoryRepository`, `IdempotencyRepository`, and `AuditSink` protocols.

- [ ] **Step 1: Write explicit remember tests**

Test that:

1. Workspace memory succeeds only when the principal can access the Workspace.
2. Reusing an idempotency key with identical input returns the same `memory_id`.
3. Reusing the key with different content raises `IdempotencyConflict`.
4. Requesting a Tenant-scoped procedural memory without `memory:admin` produces `needs_review` rather than Active.
5. Audit receives one allow or deny decision per command.

- [ ] **Step 2: Write correction and disable tests**

```python
updated = await service.correct(
    CorrectMemoryCommand(
        memory_id=created.memory_id,
        expected_revision=1,
        content="corrected content",
        reason="user_correction",
    ),
    principal,
)
assert updated.revision == 2
assert created.current_version.content == "original content"

await service.disable(
    DisableMemoryCommand(memory_id=created.memory_id, status=MemoryStatus.DELETED),
    principal,
)
with pytest.raises(MemoryNotFound):
    await service.get_active(created.memory_id, principal)
```

- [ ] **Step 3: Run application tests red**

```bash
uv run pytest tests/unit/application/test_explicit_memory.py -v
```

Expected: FAIL because application ports and service do not exist.

- [ ] **Step 4: Implement protocols, commands, and in-memory adapters**

Repository protocol methods use explicit Tenant parameters:

```python
class MemoryRepository(Protocol):
    async def add(self, tenant_id: UUID, memory: Memory, version: MemoryVersion) -> None: ...
    async def get(self, tenant_id: UUID, memory_id: UUID) -> MemoryRecord | None: ...
    async def append_version(
        self,
        tenant_id: UUID,
        memory: Memory,
        version: MemoryVersion,
        expected_revision: int,
    ) -> None: ...
    async def disable(
        self,
        tenant_id: UUID,
        memory_id: UUID,
        status: MemoryStatus,
        expected_revision: int,
    ) -> None: ...
```

Policy checks live in `ExplicitMemoryService`, not the in-memory repository. Every command emits an audit decision without storing full sensitive content.

- [ ] **Step 5: Run unit verification**

```bash
uv run pytest tests/unit/application/test_explicit_memory.py -v
uv run pytest tests/unit -v
uv run ruff check src tests/unit
uv run mypy src
```

Expected: all commands exit 0.

- [ ] **Step 6: Commit**

```bash
git add src/agent_memory/application src/agent_memory/infrastructure/in_memory.py tests/unit/application
git commit -m "feat: add explicit memory application service"
```

## Task 4: PostgreSQL schema and migrations

**Files:**
- Create: `compose.yaml`
- Create: `alembic.ini`
- Create: `src/agent_memory/config.py`
- Create: `src/agent_memory/infrastructure/db.py`
- Create: `src/agent_memory/infrastructure/orm.py`
- Create: `migrations/env.py`
- Create: `migrations/versions/0001_memory_foundation.py`
- Create: `tests/integration/conftest.py`
- Create: `tests/integration/test_postgres_repository.py`

**Interfaces:**
- Consumes: Task 2 domain types and Task 3 repository protocols.
- Produces: async `session_for_principal(principal)` and mapped tables for memories, memory_versions, idempotency_records, and audit_logs.

- [ ] **Step 1: Add the development database service**

Create `compose.yaml` with image `pgvector/pgvector:pg16`, healthcheck `pg_isready`, migration database/user `agent_memory`, a named volume, and port `${MEMORY_POSTGRES_PORT:-55432}:5432`. Do not place production passwords in the file; the checked-in password is explicitly `local-development-only`. `config.py` reads `MEMORY_DATABASE_URL`; the documented development value is `postgresql+psycopg://agent_memory:local-development-only@localhost:55432/agent_memory`.

- [ ] **Step 2: Write migration integration tests**

Use `PostgresContainer("pgvector/pgvector:pg16")`. Run `alembic upgrade head` with the container's migration connection, then query `pg_tables` and assert these tables exist:

```text
memories
memory_versions
idempotency_records
audit_logs
```

Assert every table contains `tenant_id`; assert `memory_versions` has a composite foreign key to `memories`; assert uniqueness of `(tenant_id, memory_id, version_number)`.

- [ ] **Step 3: Run integration test red**

```bash
uv run pytest tests/integration/test_postgres_repository.py::test_migration_creates_foundation_schema -v
```

Expected: FAIL because Alembic configuration and migration are missing.

- [ ] **Step 4: Implement async database configuration and migration**

Use SQLAlchemy async engine with psycopg. `session_for_principal` begins a transaction and executes:

```sql
SELECT set_config('app.current_tenant_id', :tenant_id, true)
```

Migration requirements:

- Enable `vector` extension for future plans but create no vector column yet.
- Use composite primary keys beginning with `tenant_id`.
- Create check constraints for Scope combinations and active status values.
- Create `current_version_id` after both core tables exist, as a deferrable composite foreign key.
- Enable and force RLS on all four tables.
- Create Tenant policies using `nullif(current_setting('app.current_tenant_id', true), '')::uuid`.
- Create a `agent_memory_app` role with `NOSUPERUSER NOBYPASSRLS`; grant only the table and sequence privileges needed by the application.
- Keep migration credentials separate from application credentials; repository and isolation tests connect as `agent_memory_app`, never as the Testcontainers superuser.
- Create indexes on `(tenant_id, status)`, `(tenant_id, workspace_id, status)`, and `(tenant_id, subject_user_id, status)`.

- [ ] **Step 5: Verify migration up and down**

```bash
export MEMORY_DATABASE_URL='postgresql+psycopg://agent_memory:local-development-only@localhost:55432/agent_memory'
docker compose up -d postgres
uv run pytest tests/integration/test_postgres_repository.py::test_migration_creates_foundation_schema -v
uv run alembic upgrade head
uv run alembic downgrade base
uv run alembic upgrade head
```

Expected: tests pass and all migration commands exit 0 against the test/dev database.

- [ ] **Step 6: Commit**

```bash
git add compose.yaml alembic.ini migrations src/agent_memory/config.py src/agent_memory/infrastructure/db.py src/agent_memory/infrastructure/orm.py tests/integration
git commit -m "feat: add tenant-isolated memory schema"
```

## Task 5: PostgreSQL repository and cross-tenant isolation

**Files:**
- Create: `src/agent_memory/infrastructure/repositories.py`
- Modify: `tests/integration/test_postgres_repository.py`
- Create: `tests/integration/test_tenant_isolation.py`

**Interfaces:**
- Consumes: Task 3 `MemoryRepository`, `IdempotencyRepository`, `AuditSink`; Task 4 async sessions and ORM.
- Produces: `PostgresMemoryRepository`, `PostgresIdempotencyRepository`, and `PostgresAuditSink`.

- [ ] **Step 1: Write repository round-trip and concurrency tests**

Create a Workspace memory, load it, append a correction using revision 1, and assert both immutable versions exist while current revision is 2. Attempt another revision-1 update and assert `RevisionConflict`.

- [ ] **Step 2: Write cross-tenant attack tests**

Use two principals and sessions. Assert Tenant B cannot:

- Select Tenant A memory by known UUID.
- Insert a version linked to Tenant A memory.
- Update Tenant A current version.
- Read Tenant A audit records.

The expected result is no row or a stable forbidden/domain error; never return the foreign resource's metadata.

- [ ] **Step 3: Run repository tests red**

```bash
uv run pytest tests/integration/test_postgres_repository.py tests/integration/test_tenant_isolation.py -v
```

Expected: FAIL because repository implementations are missing.

- [ ] **Step 4: Implement transactional repositories**

Map database integrity errors to stable domain errors. `append_version` must perform:

```sql
UPDATE memories
SET current_version_id = :new_version_id,
    revision = revision + 1,
    updated_at = :now
WHERE tenant_id = :tenant_id
  AND memory_id = :memory_id
  AND revision = :expected_revision
```

If affected rows equal zero, distinguish not found from revision conflict within the same Tenant-scoped transaction. Insert version and update aggregate in one transaction.

- [ ] **Step 5: Run all database verification**

```bash
uv run pytest tests/integration -v
uv run ruff check src/agent_memory/infrastructure tests/integration
uv run mypy src
```

Expected: all commands exit 0 and cross-tenant tests report zero leaks.

- [ ] **Step 6: Commit**

```bash
git add src/agent_memory/infrastructure/repositories.py tests/integration
git commit -m "feat: persist memories with tenant isolation"
```

## Task 6: Authenticated explicit-memory HTTP API

**Files:**
- Create: `src/agent_memory/api/auth.py`
- Create: `src/agent_memory/api/errors.py`
- Create: `src/agent_memory/api/schemas.py`
- Create: `src/agent_memory/api/routes.py`
- Create: `src/agent_memory/api/app.py`
- Create: `tests/api/conftest.py`
- Create: `tests/api/test_memory_api.py`

**Interfaces:**
- Consumes: `ExplicitMemoryService`, PostgreSQL repositories, `RequestPrincipal`.
- Produces: `create_app(settings) -> FastAPI` and the v1 endpoints for create, get, versions, correction, and logical deletion.

- [ ] **Step 1: Write authentication and Tenant binding tests**

Generate an RS256 test key pair. Create JWTs with `iss`, `aud`, `sub`, `tenant_id`, `roles`, `permissions`, and `allowed_workspace_ids`. Assert:

- Missing token returns `AUTHENTICATION_REQUIRED`.
- Wrong issuer/audience/signature returns the same external error without leaking crypto detail.
- A request body containing `tenant_id` is rejected as an extra field.
- The created record uses the Tenant from the validated token.

- [ ] **Step 2: Write API behavior tests**

Cover:

```text
POST /v1/memories                       201 active or 202 needs_review
GET  /v1/memories/{memory_id}           200 active record
GET  /v1/memories/{memory_id}/versions  200 immutable history
POST /v1/memories/{id}/versions         201 new version or 409 conflict
POST /v1/deletion-requests              202 retrieval_disabled=true
```

Assert stable error envelope:

```json
{
  "error": {
    "code": "MEMORY_SCOPE_FORBIDDEN",
    "message": "The caller cannot access this memory scope.",
    "retryable": false,
    "request_id": "non-empty"
  }
}
```

- [ ] **Step 3: Run API tests red**

```bash
uv run pytest tests/api/test_memory_api.py -v
```

Expected: FAIL because API modules are missing.

- [ ] **Step 4: Implement strict API contracts**

Pydantic request models use `ConfigDict(extra="forbid")`. JWT validation hard-codes allowed algorithm `RS256` and validates configured issuer and audience. Convert claims to `RequestPrincipal`; do not pass raw claims deeper into the application.

Every response includes `request_id`. `Idempotency-Key` is mandatory on write endpoints. The deletion endpoint calls logical disablement only; physical deletion is explicitly reported as `pending_physical_cleanup` for the later deletion plan.

- [ ] **Step 5: Run API and full verification**

```bash
uv run pytest tests/api -v
uv run pytest tests/unit tests/integration tests/api -v
uv run ruff check src tests
uv run mypy src
```

Expected: all commands exit 0.

- [ ] **Step 6: Commit**

```bash
git add src/agent_memory/api tests/api
git commit -m "feat: expose authenticated memory foundation API"
```

## Task 7: Foundation evaluation, documentation, and release gate

**Files:**
- Modify: `src/agent_memory/evals/foundation_runner.py`
- Modify: `tests/unit/evals/test_foundation_runner.py`
- Create: `README.md`

**Interfaces:**
- Consumes: all previous tasks.
- Produces: `uv run python -m agent_memory.evals.foundation_runner` with a nonzero exit when any safety or correctness case fails.

- [ ] **Step 1: Extend the evaluator tests**

Add executable cases for:

- Valid Workspace explicit memory.
- Invalid Scope combination.
- Idempotent replay.
- Stale revision rejection.
- Immediate exclusion after logical deletion.
- Tenant A known-ID attack from Tenant B.
- Unauthorized Tenant procedural memory producing `needs_review`.

Assert the runner exits 1 when any case fails and prints only case IDs and reason codes, not memory content.

- [ ] **Step 2: Run evaluator tests red**

```bash
uv run pytest tests/unit/evals/test_foundation_runner.py -v
```

Expected: FAIL because the runner does not yet execute application/API cases.

- [ ] **Step 3: Implement the acceptance runner**

The runner starts or connects to the test PostgreSQL fixture, runs migrations, executes each case through the application service, and returns these counters:

```json
{
  "total": 7,
  "passed": 7,
  "failed": 0,
  "tenant_leaks": 0,
  "deleted_memory_hits": 0
}
```

- [ ] **Step 4: Write the operator README**

Document:

- `uv sync --dev` and Python 3.12 isolation.
- `docker compose up -d postgres` and health verification.
- Alembic upgrade command.
- API start command.
- How to create a local RS256 test token without committing private keys.
- Exact curl examples for create, correct, get, versions, and delete.
- Difference between Memory, Event, State, and Knowledge.
- Foundation scope and the exclusions assigned to later plans.
- Full test and evaluator commands.

- [ ] **Step 5: Run the complete release gate**

```bash
uv sync --dev
uv run pytest -v
uv run ruff check src tests
uv run mypy src
uv run python -m agent_memory.evals.foundation_runner
git diff --check
```

Expected:

```text
All tests pass
Ruff exits 0
Mypy exits 0
Foundation evaluator: total=7 passed=7 failed=0 tenant_leaks=0 deleted_memory_hits=0
git diff --check produces no output
```

- [ ] **Step 6: Commit**

```bash
git add README.md src/agent_memory/evals tests/unit/evals tests/fixtures
git commit -m "docs: verify memory foundation workflow"
```

## Deferred follow-on plans

After this plan passes, write separate implementation plans in this order:

1. Event ingestion, Transactional Outbox, Job Queue, Worker leases, and model-independent candidate extraction.
2. Real model extractor, sensitive-content policy, consolidation, Evidence, and conflict lifecycle.
3. PostgreSQL lexical retrieval, pgvector embeddings, fusion, reranking, and Memory Context Packet.
4. Feedback aggregation, archival, deletion propagation, ObjectStore cleanup, and lineage re-evaluation.
5. Enterprise operations: quotas, admin review, trace/metrics, SaaS/private deployment, load and adversarial evaluation.
