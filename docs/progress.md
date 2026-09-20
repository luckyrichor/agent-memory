# 进展记录

本仓库已经发生的进展、验证结果、失败与返工。汇总看板在 `workplan-docs/进度总览.md`，排期在 `workplan-docs/总节奏表.md`，设计取舍在 `docs/design-decisions.md`。

按时间倒序，最新的写在最上面。

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
