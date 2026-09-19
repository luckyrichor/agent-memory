# AGENTS.md

本文件为在本仓库工作的编码 agent 提供指引（Claude Code 读 `CLAUDE.md`、Codex 读 `AGENTS.md`，两者都指向这里）。

## 这是什么

企业级 Agent 跨会话记忆系统。它同时是求职计划里**项目 ④（对应岗位 01：腾讯 AI 记忆系统研发专家）**的载体，总计划见 `luckyrichor/workplan-docs`。

仓库有两部分，边界必须清楚：

- **`src/agent_memory/`** —— 本项目本体，构建/测试/发布的全部范围。
- **`reference/claude-prototype/`** —— 外部参考原型，另一套独立实现，**不参与构建、不可 import**，只作为 Phase 3–5 的设计输入。详见 `reference/README.md`。

## 环境与命令

Python 3.12（`uv` 管理），PostgreSQL 走 Docker，本机不装数据库。

```bash
uv sync --all-groups              # 重建 .venv（约 150M，可随时删了重建）
docker compose up -d postgres     # pgvector/pgvector:pg16，端口 55432
uv run alembic upgrade head
```

发布门（四条都要过）：

```bash
uv run pytest -v
uv run ruff check src tests migrations
uv run mypy src                   # strict 模式
uv run python -m agent_memory.evals.foundation_runner
```

跑单个测试：

```bash
uv run pytest tests/unit/domain/test_jobs.py::test_claim_rejects_active_lease -v
uv run pytest tests/unit -q       # 只跑不依赖 Docker 的部分
```

Worker（完整参数见 README）：

```bash
uv run python -m agent_memory.workers.extraction dispatch --tenant-id <uuid> --once
uv run python -m agent_memory.workers.extraction work --tenant-id <uuid> --worker-id w1 --once
```

**`tests/api` `tests/integration` `tests/e2e` 走 Testcontainers**，Docker daemon 不可用时会直接抛 `DockerException` 而不是跳过 —— 那是环境问题不是代码问题。

**Docker 默认跑在 `tx` 服务器上**（见下方「Docker 运行位置」）。tx 上 Postgres 已常驻，`ubuntu` 已加入 docker 组，Testcontainers 可直接使用。

### 基线状态（2026-09-19 在 tx 上完整验证）

| 门 | 结果 |
|---|---|
| `uv run pytest` | **75 passed**（含 19 个 Testcontainers 测试） |
| `uv run ruff check src tests migrations` | All checks passed |
| `uv run mypy src`（strict） | 39 文件无错 |
| `evals.foundation_runner` | 8/8，0 租户泄漏，0 删除命中 |
| `alembic upgrade head` | 三条迁移全部成功 |

这是**完整**基线，不是「除了需要 Docker 的部分」。已验证的包括：RLS 跨租户隔离（已知 ID 攻击）、迁移建表与 pgvector 扩展、Postgres 仓储与内存仓储行为一致、Event 摄取的原子性与幂等、Outbox 派发幂等、Job 租约防抢占与过期恢复、API 的 JWT 租户绑定与版本生命周期、Event→Evidence→MemoryVersion 完整血缘。

**在此基础上改动后，四道门都要重新跑过再提交。**

## 架构：六边形分层，依赖单向朝内

```
api/          FastAPI 路由、JWT 认证、错误映射
  ↓
application/  用例服务 + Protocol 定义的端口（ports.py / event_ports.py）
  ↓
domain/       纯领域对象，frozen dataclass，零 I/O 零框架依赖
  ↑
infrastructure/  端口的适配器：SQLAlchemy 仓储 + 内存仓储（两套实现同一组 Protocol）
workers/      CLI 入口，把 application 的服务接到长驻循环上
evals/        用内存适配器跑的场景评估，不碰数据库
```

`infrastructure/in_memory*.py` 与 `repositories.py` / `event_repositories.py` 是同一批 Protocol 的两套实现 —— 这是单测和 evals 能秒跑、只有集成测试才需要 Docker 的原因。**加新用例时先在 `application/*_ports.py` 定义 Protocol，两套适配器都要实现**，否则 evals 会掉队。

## 核心不变量（改代码时不能破坏）

- **租户身份只来自 JWT**。请求体里出现 `tenant_id` 一律拒绝。API 连接**不得**使用数据库 owner，因为 owner 绕过 RLS；迁移里建了 `agent_memory_app` 角色（`NOSUPERUSER NOBYPASSRLS`）。
- **PostgreSQL 强制 RLS**：每张表 `ENABLE` + `FORCE ROW LEVEL SECURITY`。
- **记忆版本不可覆盖**。纠正走 `POST /versions` 追加新版本，`expected_revision` 做乐观并发。删除是逻辑删除；状态机 8 态，`deleted` 是终态。
- **Event 不可变**，`(tenant_id, idempotency_key)` 幂等；同键不同内容、或同 session 重复 sequence，都返回稳定 409。
- **Event 与 Outbox 同事务落库**，再由 dispatcher 幂等转 Job。Job 30 秒租约、指数退避上限 300 秒、5 次后进 `dead`。
- **候选记忆不得扩大 scope**：`ExtractionWorker` 显式检查 `candidate.scope != event.draft.scope` 并判为不可重试失败。
- **日志和 CLI 输出不得包含 Event 正文或记忆正文**，只输出计数、ID、结果和原因码。
- 高风险组合（procedural + tenant scope + 无 `memory:admin`）自动落到 `needs_review` 而非 `active`。

## 已实现 vs 未实现

**不要把未实现的说成已完成**，README「当前边界」一节是权威口径。

已有 —— 三类记忆、四类 scope、JWT + 权限 + RLS、幂等创建、乐观并发、不可覆盖版本、逻辑删除、审计、pgvector 扩展和向量字段（**只建了字段，没有检索逻辑**）、Event 批量摄取、事务 Outbox、幂等 Job、租约重试死信、确定性规则提取、Event→Evidence→MemoryVersion 血缘。

未有 —— 见下方路线。

## 开发路线（Phase 3–5）

设计依据是 `docs/superpowers/specs/2026-08-30-enterprise-agent-memory-system-design.md`，改架构前先读第 19 节阶段划分和第 20 节的 10 条验收标准。

**第一梯队**（岗位 01 直接考 + 被 `agent-ops-platform` 依赖）

- **混合检索**：PG 全文 + pgvector 向量 + 结构化过滤三路候选，可解释融合与重排。含 **embedding worker**（现在完全没有生成 embedding 的管道）。
- **Context Builder + Token 预算**：spec 10.5 的 Memory Context Packet，未实现。
- **可观测性**：现在零 trace、零 metrics、零结构化日志，spec 第 17 节规划的四层评测全空。
- **基线对比评测**：spec 验收标准第 10 条要求对比 No Memory 和 Naive Vector 两条基线，未实现。
- **Python SDK**：spec 12.1 规划未写；`agent-ops-platform` 要调用本服务。

**第二梯队** —— 生命周期补全（supersede / archive / 物理删除执行，现在 DeletionRequest 只落库）、Consolidation Engine、MemoryRelation（spec 8.5 列了但表未建）、Feedback Service、真实 LLM 提取器替换确定性规则、评测扩容（现在只有 8 场景 1 条 golden）。

`MemoryExtractor` 是 Protocol，本来就是为替换设计的 —— 换 LLM 提取器不需要动 worker。

## 密钥与产物

- `.local/` 存本地密钥（JWT 私钥、`ark.env` 里的 `ARK_API_KEY`），已被 `.gitignore` 忽略。**不要读其值、不要打印、不要提交。**
- 仓库里出现的 `local-development-only` / `local-app-only` 是**故意写死的本地开发占位口令**，不是泄露；生产账号应由密钥管理系统创建轮换。
- `.venv`（~150M）和 mypy/ruff/pytest 缓存是可重建产物，`uv sync --all-groups` 即可还原。
- **移动仓库目录后 `.venv` 必定失效** —— 里面的 shebang 和 `pyvenv.cfg` 写的是绝对路径，会报 `bad interpreter`。搬完先 `rm -rf .venv && uv sync --all-groups`，不要试图修补。

## 多机协作

本仓库会在 Mac、tx 服务器（Ubuntu 24.04）、Windows 之间流转，GitHub 是唯一事实源。**开工前 `git pull`，收工前 `git push`，不留未推送的提交过夜。** 同一时间只在一台机器上改。

## Docker 运行位置（用户明确要求）

**需要 Docker 时默认跑在 `tx` 服务器上**，不要在 Mac 或 Windows 上起容器。

确有必要在本地跑时，**必须先征得用户同意**，不要自行决定。

tx 上 `ubuntu` **已加入 `docker` 组**（2026-09-19），docker 命令不需要 `sudo`，Testcontainers 也可直接用。该机内存只有 7.5G，多个服务同时跑之前先看 `free -h`。

### 在 tx 上跑 Docker／测试前，必须先同步代码

本地改完直接去 tx 跑，而 tx 上还是旧代码 —— 结果是「测试通过」测的其实是旧版本，**这种假通过比失败更危险**。

用 `workplan-docs/scripts/run-on-tx.sh` 代替手工 ssh，它强制执行正确顺序：

```bash
bash workplan-docs/scripts/run-on-tx.sh agent-memory 'uv run pytest -q'
bash workplan-docs/scripts/run-on-tx.sh agent-memory 'docker compose up -d postgres'
```

它会：本地有未提交改动就拒绝 → push → tx pull → **校验两边哈希一致** → 才执行。哈希比对是最终判据，不是「命令有没有报错」。脚本还顺带剥掉了腾讯云登录横幅。

## 记录规范：新内容写到哪儿

**本仓库的正文只维护 `AGENTS.md` 一份**，`CLAUDE.md` 永远只是几行指路。两份都写正文必然漂移，**不要往 `CLAUDE.md` 里加任何内容**。

| 内容类型 | 去处 |
|---|---|
| 本仓库的指引、约定、边界、分工方式 | 本仓库 `AGENTS.md` |
| 环境、机器、工具链、跨平台的坑 | `workplan-docs/环境与踩坑记录.md` |
| 已经发生的进展、验证结果、失败与返工 | 本仓库 `docs/progress.md` |
| 关键设计取舍及其理由（面试要讲的） | 本仓库 `docs/design-decisions.md` |
| 排期、工时预算、里程碑 | `workplan-docs/总节奏表.md` |
| 岗位要求本身 | `workplan-docs/岗位要求原文.md`（唯一事实来源，不要在别处改写） |

写进「环境与踩坑记录」时，用 **［实测］**／**［预警］** 标注区分「已验证的事实」和「未触发的已知风险」，不要把推断写成结论。
