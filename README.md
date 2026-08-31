# Agent Memory

这是企业级 Agent Memory 的前两阶段实现：它已经具备显式记忆写入、作用域授权、不可覆盖的版本历史、租户隔离、逻辑删除、审计和 JWT API；同时新增了 `Event → Outbox → Job → Candidate Memory` 的异步自动提取骨架。

## 先回答 PostgreSQL 安装问题

本项目**不要求在 Mac 本机安装 PostgreSQL 或 pgvector**。本机只需：

- Python 3.12 由 `uv` 隔离管理；
- Docker Desktop 运行 `pgvector/pgvector:pg16` 容器；
- `psql` 也通过容器执行，不需要本机安装。

## 本地启动

在项目根目录执行：

```bash
uv sync --dev
docker compose up -d postgres
docker compose ps
uv run alembic upgrade head
```

`docker compose ps` 中 PostgreSQL 应显示 `healthy`。Alembic 使用数据库所有者执行建表和授权；API 不应使用数据库所有者连接，因为所有者会绕过 PostgreSQL RLS。创建一个仅用于本地开发的非超级用户：

```bash
docker compose exec postgres psql -U agent_memory -d agent_memory -c "DO \$\$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'agent_memory_local') THEN CREATE ROLE agent_memory_local LOGIN PASSWORD 'local-app-only' NOSUPERUSER NOBYPASSRLS; END IF; END \$\$; GRANT agent_memory_app TO agent_memory_local;"
```

生产环境应由密钥管理系统创建和轮换应用账号，不能复用这里的本地密码。

## 创建本地 RS256 身份

私钥只放在被 Git 忽略的 `.local/` 目录，不提交到仓库：

```bash
mkdir -p .local
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out .local/jwt-private.pem
openssl rsa -pubout -in .local/jwt-private.pem -out .local/jwt-public.pem

export MEMORY_DATABASE_URL='postgresql+psycopg_async://agent_memory_local:local-app-only@localhost:55432/agent_memory'
export MEMORY_JWT_PUBLIC_KEY="$(<.local/jwt-public.pem)"
export MEMORY_JWT_ISSUER='memory-local'
export MEMORY_JWT_AUDIENCE='memory-api'
```

生成一个五分钟有效的开发令牌：

```bash
export TOKEN="$(uv run python -c 'from datetime import UTC,datetime,timedelta; from pathlib import Path; import jwt; now=datetime.now(UTC); print(jwt.encode({"iss":"memory-local","aud":"memory-api","sub":"30000000-0000-0000-0000-000000000002","tenant_id":"30000000-0000-0000-0000-000000000001","roles":["developer"],"permissions":["memory:read","memory:write","memory:delete"],"allowed_workspace_ids":["project-a"],"iat":now,"exp":now+timedelta(minutes=5)},Path(".local/jwt-private.pem").read_text(),algorithm="RS256"))')"
```

启动 API：

```bash
uv run uvicorn agent_memory.api.app:create_app_from_env --factory --host 127.0.0.1 --port 8000
```

## API 操作示例

### 接入不可变 Event

Agent 通过严格的批量接口上报工具结果。当前 API 只接受 `tool.result`，正文不允许携带 `tenant_id`：租户和用户身份必须来自 JWT。

```bash
curl -sS -X POST http://127.0.0.1:8000/v1/events:batch \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{
    "events": [
      {
        "idempotency_key": "build-project-a-001",
        "session_id": "coding-session-001",
        "sequence_number": 1,
        "event_type": "tool.result",
        "agent_id": "coding_agent",
        "occurred_at": "2026-08-30T12:00:00Z",
        "scope": {"kind": "workspace", "workspace_id": "project-a"},
        "payload": {
          "tool_name": "build",
          "exit_code": 1,
          "summary": "x86_64 dependency failed on arm64",
          "error_code": "ARCH_MISMATCH"
        }
      }
    ]
  }'
```

首次接入返回 `accepted`；相同 `idempotency_key` 与相同内容重放返回原 `event_id` 和 `duplicate`。同一幂等键内容变更，或同一 session 重复占用 sequence，都会返回稳定的 `409` 冲突。

### 显式记忆

创建 Workspace 记忆；租户 ID 只能来自 JWT，正文不能指定：

```bash
curl -sS -X POST http://127.0.0.1:8000/v1/memories \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Idempotency-Key: remember-project-a-001' \
  -H 'Content-Type: application/json' \
  -d '{"content":"项目 A 使用 Java 17","memory_type":"semantic","scope":{"kind":"workspace","workspace_id":"project-a"}}'
```

从响应中复制 `memory_id`：

```bash
export MEMORY_ID='把创建响应中的 memory_id 填在这里'
```

读取当前生效版本：

```bash
curl -sS "http://127.0.0.1:8000/v1/memories/$MEMORY_ID" \
  -H "Authorization: Bearer $TOKEN"
```

纠正记忆会新增版本，不覆盖旧正文。`expected_revision` 用于阻止并发旧写入：

```bash
curl -sS -X POST "http://127.0.0.1:8000/v1/memories/$MEMORY_ID/versions" \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"expected_revision":1,"content":"项目 A 已升级为 Java 21","reason":"user_correction"}'
```

查看完整版本历史：

```bash
curl -sS "http://127.0.0.1:8000/v1/memories/$MEMORY_ID/versions" \
  -H "Authorization: Bearer $TOKEN"
```

逻辑删除会立即停止检索；物理清理任务将在后续 worker 阶段实现：

```bash
curl -sS -X POST http://127.0.0.1:8000/v1/deletion-requests \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Idempotency-Key: delete-project-a-001' \
  -H 'Content-Type: application/json' \
  -d "{\"memory_id\":\"$MEMORY_ID\",\"expected_revision\":2}"
```

## 运行异步提取

API 接入 Event 时，Event 和 Outbox 在同一个数据库事务中落库。dispatcher 再将 Outbox 幂等地转换为 Job，worker 对 Job 提取 Candidate Memory 并建立 Event 到 MemoryVersion 的 Evidence 血缘。

先运行一次 dispatcher：

```bash
uv run python -m agent_memory.workers.extraction dispatch \
  --tenant-id 30000000-0000-0000-0000-000000000001 \
  --once
```

再处理一个 Job：

```bash
uv run python -m agent_memory.workers.extraction work \
  --tenant-id 30000000-0000-0000-0000-000000000001 \
  --worker-id worker-local-1 \
  --once
```

去掉 `--once` 就会持续轮询；轮询间隔只允许 1–60 秒，例如：

```bash
uv run python -m agent_memory.workers.extraction dispatch \
  --tenant-id 30000000-0000-0000-0000-000000000001 \
  --poll-seconds 2

uv run python -m agent_memory.workers.extraction work \
  --tenant-id 30000000-0000-0000-0000-000000000001 \
  --worker-id worker-local-1 \
  --poll-seconds 2
```

`SIGINT`/`SIGTERM` 会让循环优雅停止。Job 领取后持有 30 秒租约，租约过期可由其他 worker 重新领取；显式的可重试提取错误会进入 `retry_wait`，指数退避最长 300 秒，最多 5 次尝试后进入 `dead`；无效 Event 等不可重试错误会直接进入 `dead`。CLI 只输出计数、Job ID、结果和原因码，不输出 Event 或记忆正文。

这一阶段没有增加新的 Python 依赖；所有现有依赖仍由 `uv sync --dev` 安装到项目 `.venv` 中。

## 五个容易混淆的概念

| 概念 | 作用 | 例子 | 是否属于本阶段 |
|---|---|---|---|
| Memory | 可跨回合复用、受治理的长期信息 | “项目 A 使用 Java 21” | 是 |
| Event | 发生过的不可变业务事实，可驱动后续处理 | 一次构建命令失败 | 是 |
| Audit | 记录谁在何时对 Memory 做了什么，用于治理与追责 | 某用户纠正了一条记忆 | 是 |
| State | 当前工作流的精确运行状态 | 当前任务步骤、工具调用游标 | 否，应由工作流系统管理 |
| Knowledge | 文档、代码和制度等可查询资料 | 仓库源码、企业规范文档 | 否，应由知识/RAG 系统管理 |

Event 记录“发生了什么”，一旦接入不会就地覆盖；Audit 记录“谁对记忆做了什么”。两者都不等于 Memory：只有通过提取、作用域、置信度和治理规则的信息，才能成为可跨回合复用的 Memory。Memory 也不是向量数据库中的一行：PostgreSQL 中的版本化记录是事实源，embedding 只是可删除、可重建的检索索引。

## 当前边界

本阶段已经包含：

- episodic、semantic、procedural 三类显式记忆；
- tenant、workspace、user_global、user_workspace 四类作用域；
- JWT 身份绑定、权限检查、PostgreSQL 强制 RLS；
- 幂等创建、乐观并发、不可覆盖版本、逻辑删除、审计；
- pgvector 扩展和向量字段的数据库基础；
- 不可变 Event 批量接入、事务 Outbox、幂等 Job；
- 租约领取、退避重试、死信终态和可恢复 worker；
- 对 build/test 失败的确定性规则提取，以及 Event → Evidence → MemoryVersion 血缘。

后续阶段依次实现：真实模型提取与敏感信息策略；全文与向量混合检索；反馈、归档和物理删除传播；配额、管理审核、可观测性和压测。当前的提取器是可验证的确定性规则，不是 LLM 提取；不要把这些未实现能力描述成已经完成。

## 验证与发布门

```bash
uv run pytest -v
uv run ruff check src tests migrations
uv run mypy src
uv run python -m agent_memory.evals.foundation_runner
git diff --check
```

基础评估覆盖 8 个安全/正确性场景，包含自动提取重放场景，输出不包含 Event 或记忆正文。应用层评估使用可替换的内存适配器以便快速运行；PostgreSQL 迁移、真实仓储、RLS 已知 ID 攻击、API 生命周期和完整候选记忆血缘由集成/E2E 测试通过 Testcontainers 验证。

停止本地数据库但保留数据：

```bash
docker compose down
```
