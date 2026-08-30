# Event Ingestion and Asynchronous Extraction Design

## 1. 目标

在现有 Memory Foundation 上实现企业 Agent 的自动学习入口：Agent 批量提交允许持久化的工作事件，服务将 Event 与 Outbox 原子写入 PostgreSQL，再由数据库队列和带租约 Worker 异步生成候选记忆及 Evidence。

第一条端到端场景是 Coding Agent 构建失败经验：`tool.result` 事件包含构建或测试工具的非零退出码与安全摘要，规则提取器生成 Workspace 级 episodic Candidate Memory，并通过 Evidence 指回原始 Event。

## 2. 已批准的技术路线

采用 PostgreSQL 原生 Outbox 和 Job Queue，不引入 Redis、Kafka 或 RabbitMQ。

选择原因：

- Event、Outbox、Job 和候选 Memory 可以共享事务边界。
- `FOR UPDATE SKIP LOCKED` 足以支撑当前单服务及少量 Worker。
- SaaS 和私有化部署都只增加已有 PostgreSQL 依赖。
- 当真实吞吐指标证明 PostgreSQL 成为瓶颈后，Outbox Publisher 接口允许替换为消息平台。

被否决的当前方案：Redis 会引入数据库与队列双写；Kafka 会提前引入分区、消费组、Schema Registry 和额外运维。两者不是永久排除，而是推迟到有测量依据之后。

## 3. 范围

本阶段包含：

- JWT 认证的 Event 批量摄取 API。
- Tenant、Scope、Workspace 权限和 Session sequence 校验。
- Event 幂等与同键异内容冲突。
- Event 与 Outbox 同事务写入。
- Outbox 到 Job 的原子派发。
- Job 租约、并发领取、续租边界、成功、重试和 Dead Letter。
- 可替换 `MemoryExtractor` 接口。
- 确定性 Coding Build Failure 规则提取器。
- Candidate Memory 和 Evidence 原子写入。
- 跨租户 RLS、重复投递、崩溃恢复和并发 Worker 测试。
- 单次派发、单次 Worker 和持续 Worker CLI。

本阶段不包含：

- 真实 LLM 调用、Prompt 管理和模型供应商配置。
- 完整敏感信息识别与数据出境策略。
- 多事件窗口合并、语义去重和冲突图。
- Candidate 审核 API 和自动激活策略。
- 向量生成、混合检索和 Context Packet。
- Kafka、Redis、Kubernetes 或独立微服务部署。

## 4. 核心不变量

1. Tenant 只来自验证后的 JWT，Event 请求体不能选择 Tenant。
2. Event Scope 必须与 Principal 权限一致；Worker 不得扩大 Scope。
3. Event 和对应 Outbox 必须在同一数据库事务提交或回滚。
4. 投递语义为至少一次；业务效果通过自然幂等键实现至多一次。
5. Event 不可修改，只允许在后续生命周期阶段按删除策略清理。
6. Worker 只处理自己持有且未过期的租约。
7. Candidate Memory、MemoryVersion、Evidence 和 Job 成功状态在同一事务提交。
8. Event Payload 不保存模型隐藏推理、访问令牌、私钥或完整环境变量。
9. 所有新表的主键、唯一键和外键都包含 `tenant_id`，并启用强制 RLS。
10. 普通应用数据库角色保持 `NOSUPERUSER NOBYPASSRLS`。

## 5. 数据模型

### 5.1 events

不可变工作证据。

| 字段 | 类型 | 规则 |
|---|---|---|
| tenant_id | UUID | 复合主键、RLS |
| event_id | UUID | 复合主键，由服务端生成 |
| idempotency_key | varchar(255) | Tenant 内唯一 |
| request_hash | char(64) | 规范化请求 SHA-256 |
| session_id | varchar(255) | 必填 |
| sequence_number | bigint | 正整数；Tenant + Session 内唯一 |
| event_type | varchar(64) | 当前允许 `tool.result`、`task.completed`、`user.confirmed` |
| scope_kind | varchar(32) | 与 MemoryScope 同构 |
| workspace_id | varchar(512) | Scope 约束 |
| subject_user_id | UUID | Scope 约束 |
| actor_user_id | UUID | 来自 JWT Principal |
| agent_id | varchar(255) | 调用 Agent 的稳定标识 |
| occurred_at | timestamptz | Agent 观察到事件的时间 |
| received_at | timestamptz | 服务接收时间 |
| payload | jsonb | 严格限制后的结构化内容 |

唯一约束：

- `(tenant_id, idempotency_key)`
- `(tenant_id, session_id, sequence_number)`

同一 Idempotency-Key 与同一规范化请求返回原 Event；同键异内容返回 `EVENT_IDEMPOTENCY_CONFLICT`。Session sequence 冲突但 Idempotency-Key 不同返回 `EVENT_SEQUENCE_CONFLICT`。

### 5.2 outbox_messages

业务事务内产生的可靠发布记录。

| 字段 | 类型 | 规则 |
|---|---|---|
| tenant_id | UUID | 复合主键、RLS |
| outbox_id | UUID | 复合主键 |
| topic | varchar(64) | 当前只有 `event.recorded` |
| aggregate_type | varchar(64) | `event` |
| aggregate_id | UUID | Event ID |
| payload | jsonb | 只包含路由所需 ID，不复制 Event 正文 |
| status | varchar(16) | `pending` 或 `published` |
| available_at | timestamptz | 派发时间门槛 |
| attempts | integer | 派发尝试次数 |
| created_at | timestamptz | 创建时间 |
| published_at | timestamptz | 成功派发时间 |

`(tenant_id, topic, aggregate_id)` 唯一，防止同一 Event 产生重复派发。

### 5.3 jobs

PostgreSQL 工作队列。

| 字段 | 类型 | 规则 |
|---|---|---|
| tenant_id | UUID | 复合主键、RLS |
| job_id | UUID | 复合主键 |
| job_type | varchar(64) | 当前只有 `extract_event` |
| idempotency_key | varchar(255) | Tenant + Job type 内唯一 |
| payload | jsonb | `{event_id, extractor_version}` |
| status | varchar(16) | `pending`、`running`、`retry_wait`、`succeeded`、`dead` |
| attempts | integer | 每次成功 claim 后加一 |
| max_attempts | integer | 默认 5 |
| available_at | timestamptz | 下次可领取时间 |
| leased_until | timestamptz | running 租约到期时间 |
| lease_owner | varchar(255) | Worker 实例 ID |
| last_error_code | varchar(64) | 稳定原因码，不保存敏感正文 |
| created_at | timestamptz | 创建时间 |
| updated_at | timestamptz | 状态更新时间 |

自然幂等键为 `extract_event:{event_id}:{extractor_version}`。

### 5.4 evidence

连接候选 MemoryVersion 与 Event。

| 字段 | 类型 | 规则 |
|---|---|---|
| tenant_id | UUID | RLS 与全部复合外键首列 |
| memory_version_id | UUID | 指向 MemoryVersion |
| event_id | UUID | 指向 Event |
| role | varchar(32) | 当前使用 `triggered_by` |
| created_at | timestamptz | 创建时间 |

主键为 `(tenant_id, memory_version_id, event_id, role)`。

## 6. API 契约

### POST /v1/events:batch

请求头：

- `Authorization: Bearer <RS256 JWT>`，必填。
- `Idempotency-Key` 不用于批次；每条 Event 自带稳定 `idempotency_key`。
- `X-Request-Id` 可选。

请求最多 100 条 Event，空批次拒绝。每条结构：

```json
{
  "idempotency_key": "session-42-build-7",
  "session_id": "session-42",
  "sequence_number": 7,
  "event_type": "tool.result",
  "agent_id": "coding_agent",
  "occurred_at": "2026-08-30T12:00:00Z",
  "scope": {"kind": "workspace", "workspace_id": "project-a"},
  "payload": {
    "tool_name": "build",
    "exit_code": 1,
    "summary": "arm64 build failed because an x86_64 dependency was selected"
  }
}
```

成功返回 `202 Accepted`：

```json
{
  "items": [
    {"event_id": "...", "idempotency_key": "session-42-build-7", "disposition": "accepted"}
  ]
}
```

重复同内容的 disposition 为 `duplicate`，并返回原 `event_id`。批次是原子的；任何条目冲突或无权访问时整个批次回滚。稳定错误码包括：

- `EVENT_BATCH_INVALID`
- `EVENT_IDEMPOTENCY_CONFLICT`
- `EVENT_SEQUENCE_CONFLICT`
- `EVENT_SCOPE_FORBIDDEN`

Payload 规则：JSON 编码后每条不超过 64 KiB；key 总数和嵌套深度由 Pydantic Schema 限制。当前 `tool.result` 只接受 `tool_name`、`exit_code`、`summary`、`error_code`，额外字段拒绝，避免误收集环境变量和密钥。

## 7. 应用接口

```python
class EventIngestionService:
    async def ingest_batch(
        self,
        command: IngestEventBatchCommand,
        principal: RequestPrincipal,
    ) -> tuple[EventIngestionResult, ...]: ...

class OutboxDispatcher:
    async def dispatch_once(self, tenant_id: UUID, batch_size: int) -> int: ...

class JobQueue:
    async def claim(
        self,
        tenant_id: UUID,
        worker_id: str,
        now: datetime,
        lease_duration: timedelta,
    ) -> Job | None: ...

    async def renew(
        self,
        tenant_id: UUID,
        job_id: UUID,
        worker_id: str,
        now: datetime,
        lease_duration: timedelta,
    ) -> bool: ...

class MemoryExtractor(Protocol):
    version: str
    async def extract(self, event: Event) -> tuple[MemoryCandidate, ...]: ...

class ExtractionWorker:
    async def run_once(self, worker_id: str) -> WorkerResult: ...
```

领域对象不依赖 SQLAlchemy、FastAPI 或具体模型供应商。Repository 端口显式接收 Tenant；PostgreSQL 适配器再通过 RLS 提供第二层隔离。

## 8. 数据流与事务

### 8.1 摄取事务

```text
JWT → Principal → Batch/Scope/Payload validation
    → SELECT existing idempotency keys
    → INSERT immutable Events
    → INSERT event.recorded Outbox rows
    → COMMIT
```

Event 和 Outbox 任何一步失败都回滚。重复同内容不新增 Event 或 Outbox。

### 8.2 Outbox 派发事务

```text
SELECT pending Outbox FOR UPDATE SKIP LOCKED
    → INSERT Job ON CONFLICT DO NOTHING
    → mark Outbox published
    → COMMIT
```

因为 Job 和 Outbox 同在 PostgreSQL，二者在一个事务内完成。进程在提交前崩溃会回滚并重新派发；提交后重复调用由 Job 自然幂等键吸收。

### 8.3 Worker 领取

单个短事务通过 `FOR UPDATE SKIP LOCKED` 领取一个 `pending`、到期 `retry_wait` 或租约已过期的 `running` Job，写入 `running`、`lease_owner`、`leased_until` 并增加 attempts。

不同 Worker 不等待同一行。业务处理使用新事务，并在写入前验证 Job 仍由当前 Worker 持有且租约未过期。

Dispatcher 和 Worker 都按单个 Tenant 运行，不能关闭 RLS 后进行全表扫描。本地 CLI 明确接收 `--tenant-id`；生产调度器未来从独立的 Tenant Registry 获取授权 Tenant 列表，再为每个 Tenant 建立隔离会话。Tenant Registry 不属于本阶段。

### 8.4 成功处理事务

```text
load Event under same Tenant
    → deterministic prefilter
    → MemoryExtractor.extract
    → validate candidate Scope is exactly Event Scope
    → INSERT Candidate Memory + MemoryVersion
    → INSERT Evidence(triggered_by)
    → mark Job succeeded
    → COMMIT
```

无候选也是成功结果，避免对无价值 Event 无限重试。

## 9. 规则提取器

`CodingFailureRuleExtractor.version = "coding-failure-rule-v1"`。

只有同时满足以下条件才生成候选：

- `event_type == "tool.result"`
- `payload.tool_name` 为 `build` 或 `test`
- `payload.exit_code != 0`
- `payload.summary` 去除首尾空白后非空

输出：

- `memory_type = episodic`
- `status = candidate`
- Scope 与 Event 完全一致
- content 为规范化 summary
- `confidence = 1.0`
- `utility = 0.5`
- `authority_level = tool_verified`
- `verification_status = verified`
- Evidence role 为 `triggered_by`

规则提取器用于证明管线契约，不代表完整的敏感信息策略或最终自然语言质量。

## 10. 重试、租约与失败

- 默认租约 30 秒，默认最大尝试 5 次。
- 可重试错误采用确定性指数退避：`min(2 ** attempts, 300)` 秒，不增加随机数以保持测试稳定。
- `retry_wait` 到达 available_at 后可重新领取。
- attempts 达到 max_attempts 后进入 `dead`。
- 永久输入错误直接进入 `dead`，原因码为 `INVALID_EVENT_FOR_EXTRACTION`。
- 临时数据库或提取器错误进入 `retry_wait`，原因码使用稳定枚举。
- `last_error_code` 和日志不得存储 Event summary、Payload 或异常原文。
- 租约丢失的 Worker 不得提交候选或改变 Job 状态。

## 11. 安全

- API 在数据库查询前完成 JWT、Permission 和 Scope 校验。
- 新表全部启用 `ENABLE ROW LEVEL SECURITY` 与 `FORCE ROW LEVEL SECURITY`。
- Worker 必须按 Job Tenant 建立 `session_for_principal` 等效租户上下文；不能使用跨租户超级用户处理业务。
- Dispatcher 与 Worker 的每次 claim 都显式携带 Tenant ID；当前不存在跨 Tenant 队列扫描接口。
- Outbox Payload 只保存 Event ID 与 extractor version。
- API Schema `extra="forbid"`，避免把完整工具环境或模型隐藏推理误写入 Event。
- 已知 Event ID、Outbox ID 或 Job ID 不能被其他 Tenant 读取、领取、关联或推断。

## 12. 测试与验收

单元测试：

- Scope 与 Payload 校验。
- Event 请求规范化 Hash。
- 同键同内容幂等、同键异内容冲突。
- 规则提取器命中与预筛选。
- Worker 退避、最大尝试和租约丢失。

PostgreSQL 集成测试：

- 迁移升级/降级和所有约束。
- Event + Outbox 原子性。
- 重复 Event 不产生重复 Outbox。
- 两个 Dispatcher 不生成重复 Job。
- 两个 Worker 并发 claim 不得到同一 Job。
- 过期租约可恢复，未过期租约不可抢占。
- Candidate、Version、Evidence、Job success 原子提交。
- Tenant B 已知 ID 攻击在 Event、Outbox、Job、Evidence 上均失败。

API 测试：

- 缺失 JWT 返回 401。
- 请求体携带 tenant_id 返回 422。
- 无权 Workspace 返回 403。
- 有效批次返回 202。
- 重放返回原 Event ID 与 duplicate disposition。

端到端验收：同一构建失败 Event 重放两次，最终数据库中恰好存在一个 Event、一个已发布 Outbox、一个成功 Job、一个 Candidate Memory、一个 MemoryVersion 和一条 Evidence；Candidate Scope 与 Event Scope 相同。

## 13. 运行与依赖

- Python 保持 `>=3.12,<3.13`。
- 所有 Python 依赖只通过 `uv add`、`uv add --dev`、`uv sync --dev` 进入项目 `.venv`。
- 当前设计不需要新增 Python 包；继续使用 FastAPI、Pydantic、SQLAlchemy、psycopg、Alembic 和 pytest。
- PostgreSQL/pgvector 继续通过 Docker，Mac 不安装原生数据库。
- Worker CLI 使用 `uv run python -m agent_memory.workers.extraction`。

## 14. 完成定义

本阶段完成必须同时满足：

- 所有单元、集成和 API 测试通过。
- Ruff、mypy 和 `git diff --check` 通过。
- 端到端重复事件验收通过且计数全部为 1。
- RLS 已知 ID 攻击测试通过。
- Worker 日志安全测试证明不输出 Event 正文。
- README 包含批量 Event curl、Dispatcher、单次 Worker 和持续 Worker 命令。
- Docker 仅在集成测试和本地运行时需要，完成后可关闭。
