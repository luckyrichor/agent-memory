# 进展记录

## 2026-10-02 火山1024维适配与M4真实初验（Codex）

来源agent-memory@462ec1a + 本次工作树修改。统一API/校验/ORM/夹具为1024维；增加Ark协议，worker/API统一Settings。0006清旧向量并排重建，保留记忆版本；新增两租户迁移验证。120 tests、ruff、strict mypy56、foundation8/8通过。

真实doubao-embedding-vision-251215完成worker→独立PostgreSQL→JWT查询API：5条改写Top1均命中，全文/结构化均0命中；0租户泄漏、0删除命中。M4初验通过，非生产统计。报告含实际源码哈希，详见docs/ark-integration.md。

tx常驻空库先备份再0003→0006，vector(1024)、记忆/版本仍0/0，无存量重建任务；未新增常驻服务。密钥只存忽略目录，未进Git。

最后更新：2026-10-02（北京时间）

本仓库已经发生的进展、验证结果、失败与返工。汇总看板在 `workplan-docs/进度总览.md`，排期在 `workplan-docs/总节奏表.md`，设计取舍在 `docs/design-decisions.md`。

按时间倒序，最新的写在最上面。

---

## 2026-10-01 W3 / M3 自动验收通过（Codex）

来源 agent-memory@5b9ee55 + 未提交修改，tx；严格在 M2 四道门通过后实现。

新增 application/embedding.py、两套 embedding backend、HTTP/夹具 provider、worker CLI、0004 迁移及 pgvector memory_embeddings。版本写入自动同事务排队，按 job_type 隔离提取/embedding，失败重试/持久 dead/重建，租约校验与落库原子提交。详见 docs/embedding-worker.md。

本次四道门：pytest **109 passed in 6.43s**；ruff 通过；mypy strict **52 source files** 通过；foundation_runner **8/8，0 泄漏、0 删除命中**。首次全量 1 failed/106 passed：旧提取端到端测试把 embedding Job 误算作重复提取任务，改为分别断言提取与 embedding 任务后全量通过。迁移 round-trip 随全量测试通过。

向量实际在 Postgres 落库，异步队列与重启恢复已验证；本次使用确定性夹具向量及 HTTP mock，不声称线上语义模型或混合检索已验收。0004 迁移仅在 Testcontainers 中实跑，未改常驻数据库。未提交/推送，未虚构工时。

---

## 2026-10-01　W2 / M2 自动验收通过（Codex）

来源：agent-memory@5b9ee55 + 本次未提交修改；执行机器 tx。未提交、未推送。

- 增加异步 HTTP SDK（remember/get/correct/delete/archive/supersede），调用方持有认证 token 与 HTTP client 生命周期。SDK 不输出正文/凭据，不自动重试非幂等写。
- archive/supersede 路由复用领域禁用状态机，保留旧版本；非法状态返回 409。
- 删除 Idempotency-Key 持久保存结果，包含操作、目标、revision 的请求哈希；同键异参 409。Postgres 事务级 advisory lock 串行同租户同 key，并发重放不重复修改 revision。
- 新增真实 ASGI + Postgres SDK 生命周期/并发删除测试、AST 日志边界测试，禁止业务代码直接 import logging（包括 alias/from import）。
- 本次四道门：pytest **106 passed in 6.97s**（sg docker，全量）；ruff 通过（首次两处 import 排序失败已修正）；mypy strict **48 source files** 通过；foundation_runner **8/8，0 tenant_leaks，0 deleted_memory_hits**。
- 物理清理执行者仍未实现，删除返回 pending_physical_cleanup 不代表已物理删除。分页/混合检索仍属后续里程碑。

---

## 2026-09-20　M1 可观测性地基　完成

排期：W1 主力档，预估 5 h。

### 做了什么

新增叶子包 `src/agent_memory/observability/`（`fields` / `logging` / `tracing` / `metrics` / `context` / `setup`），并接到三条路径上：

- **API**：`api/middleware.py` 生成或沿用 `X-Request-Id`，开最外层 span，出口记录访问日志与指标；`auth.py` 在 JWT 解析成功后把租户绑到 span 与 `request.state`。
- **应用层**：`ExplicitMemoryService` 的 remember / get_active / correct / disable 四个用例各自成 span，并在每个结果分支发一条日志和一个计数（`_observe`）；`EventIngestionService` 同理。
- **提取侧**：`ExtractionWorker.run_once` 成 span，worker CLI 每轮循环开一个新的 `request_id`。
- **数据库**：`session_for_principal` 开 `db.session` span，写入请求因此能看到 HTTP → 会话 → 用例三层。

指标四个：`agent_memory.http.requests`、`agent_memory.http.duration`、`agent_memory.memory.operations`、`agent_memory.worker.jobs`。

导出默认 `none`，用 `MEMORY_TRACE_EXPORTER` / `MEMORY_METRICS_EXPORTER` 打开。

### 验收对照

| 验收标准 | 证据 |
|---|---|
| 一次完整的写入/检索请求能在 trace 中看到全链路 span | `tests/api/test_observability_api.py`：真实 ASGI + Testcontainers Postgres，断言 `POST /v1/memories` 为根 span、`db.session` 与 `memory.remember` 同 trace；读路径断言 `memory.get_active` 的 `reason_code=MEMORY_RETURNED` |
| 有结构化日志与基础 metrics | `tests/unit/observability/test_logging.py`（JSON 形状、关联 ID、trace_id 对齐）、`test_metrics.py`（计数与直方图共用标签、路由模板不用具体路径） |
| 日志与 CLI 输出不含 Event 正文或记忆正文 | `test_no_span_or_log_line_carries_the_memory_content`、`test_worker_telemetry_never_carries_the_extracted_content`：把导出的 span JSON 和日志字段整体搜一遍正文子串 |

四道门（在 tx 上跑）：`pytest` **103 passed**（基线 75 + 新增 28）、`ruff` 通过、`mypy --strict` 47 文件无错、`foundation_runner` 8/8、0 租户泄漏、0 删除命中。

### 过程中发现并修掉的三个真问题

1. **alembic 会静默禁掉应用的 logger**。`migrations/env.py` 里的 `fileConfig()` 默认 `disable_existing_loggers=True`，把迁移之前（即模块导入时）创建的 logger 全部 `disabled=True`。表现是服务照常工作、日志无声无息地没了。已改为 `disable_existing_loggers=False`，并用 `tests/integration/test_migration_logging.py` 钉住。
   这个坑是在「单跑测试通过、全量跑失败」时才暴露的 —— 单跑时迁移还没执行过。
2. **日志格式化时机晚于上下文销毁**。原实现在 `JsonFormatter.format()` 里读关联 ID 和 span ID，而格式化可能发生在上下文退出之后（异步 handler、QueueHandler 更明显），字段就丢了。改为**发出时即刻捕获**，格式化只负责渲染。
3. **`configure_logging` 原本摘掉 root 上的全部 handler**，等于接管宿主进程的日志配置，也把 pytest 的捕获 handler 一并摘掉。改为只替换自己打了标记的 handler，重复调用幂等。

### 没做的部分（不要当成已完成）

- 没有接任何后端：OTLP 导出、采样策略、告警、看板都没有，导出器只有 `console`。
- spec 第 17 节的四层评测仍然是空的，M1 只是给它备好了信号通路。
- 数据库 span 只到会话粒度，没有逐条 SQL 的 span（未接 SQLAlchemy instrumentation）。
- `correct` / `disable` 的失败分支没有单独的 deny 计数，只有成功分支；remember 与 get_active 两条路径是全的。

---

## 2026-09-19　基线完整验证

在 tx 上跑通全部四道门：`pytest` 75 passed（含 19 个 Testcontainers 测试）、`ruff` 通过、`mypy --strict` 39 文件无错、`foundation_runner` 8/8、`alembic upgrade head` 三条迁移成功。

已验证内容见 `AGENTS.md`「基线状态」一节。这是完整基线，不是「除了需要 Docker 的部分」。

## 2026-10-01 W4 维持 / CI 配置与本地核验（Codex）

来源 agent-memory@5b9ee55 + 未提交修改，tx；与 W2 M2、W3 M3 分别记录。新增 `.github/workflows/ci.yml`（push/pull_request、只读 contents、Ubuntu Docker、Python 3.12、uv frozen、15 分钟超时）及 `scripts/check.sh`，四道门 fail-fast。

YAML 解析与入口/权限/触发器核验通过，bash -n 通过；本次用 `sg docker -c 'bash scripts/check.sh'` 实跑：**110 passed in 6.13s**、ruff 通过、mypy --strict **52 source files** 通过、foundation_runner **8/8，0 tenant_leaks、0 deleted_memory_hits**。本次比 M3 初验新增一个删除幂等边界测试：同键异目标（不存在）仍 409、未授权重放 403、revision 不重复增加。

CI 文件已本地验证，但未提交/推送，GitHub Actions **未触发、未验证远端通过**。远端 CI 触发/结果核验为待办；用户授权提交/推送后才可执行。不是“远端 CI 全绿”。

## 2026-10-01 用户授权发布 / GitHub Actions 验收通过（Codex）

用户明确授权后，M2/M3 和 CI 配置已提交、推送为 `3c994e1`。提交前本地复验：pytest 110 passed in 5.96s、ruff 通过、strict mypy 52 文件无错、foundation 8/8。

GitHub Actions [Foundation gates #36811146053](https://github.com/luckyrichor/agent-memory/actions/runs/36811146053) 对应实际提交 `3c994e12784aad37c70e60b4fd98b5a1f4457358`，结论 success：pytest 110 passed in 14.86s、ruff 通过、strict mypy 52 文件无错、foundation 8/8（0 tenant_leaks、0 deleted_memory_hits）。W4 远端 CI 待办已验收；上节的未发布状态保留为当时的历史记录。
## 2026-10-02 W6 / M4（Codex）

来源 agent-memory@ac7712a + 本轮工作树修改；提前推进用户指定 W5–W7。实现三路混合检索、授权前置硬过滤、可解释加权 RRF、查询 HTTP embedding provider、所有列表分页（含版本），补充 SDK search 与 py.typed、GIN 索引迁移、零向量防护和内存适配器。

本轮末次四道门：118 pytest passed in 7.35s（含实际 PostgreSQL/pgvector）；ruff 通过；strict mypy 56 文件通过；foundation 8/8，0 泄漏/0 删除命中。已验证 scope/租户/user/archive/needs_review/deleted 隔离、纠正后的旧向量退出、分页与分数解释。全量过程中发现等权结构化新近排名与向量排名打平，已降低结构化权重并重新验收；未忽略失败用例。

M4 工程通过，真实语义模型效果暂跳过，不标 M4 全部完成。固定改写向量夹具只证明检索流程。详情见 docs/retrieval.md；无实际工时声明。此前章节为历史记录。


## 2026-10-07 Codex：W8–W10实际执行

M7：增加LLMExtractor与dispatch/work共同工厂，原ExtractionWorker不改；有界JSON候选、scope/authority由服务端决定、敏感模式检查、HTTP/格式错误规则回退。真实mini模型验证通过（两条非build/test事件、一条敏感事件拒绝），事件→Outbox→原worker→candidate/evidence/job真实PostgreSQL原子链路通过；candidate_count=2，0权限升级/0租户泄漏。一次在线提炼只产出1条预期模型结果、另一次触发回退，复验2条通过，线上漂移/失败不作为CI依赖。先探测lite返回429/旧flash返回404，再发现mini可用，不笼统判断整个账户不可用。

M5：真实数据库、固定M7响应与同一应用身份下，对No Memory / Naive Vector / 系统作3个合成原生C++构建故障回放；g++实际编译与程序执行，旧知识选择不兼容的header API。固定向量和真实Ark向量两组结果均0/3、1/3、3/3。初验通过，不能外推真实用户工程或一般LLM收益。M6后续仍未做；不启动常驻API/worker。

最终四道门：139 pytest passed in 9.39s；ruff通过，strict mypy57文件通过；foundation8/8，0租户泄漏/0删除命中。来源agent-memory@c5a067a + 本轮工作树；精确SHA256见docs/measurements/w8-w10-source.json，边界见docs/llm-extraction-and-baselines.md。
