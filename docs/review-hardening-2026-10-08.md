# Agent Memory 外部评审修复（2026-10-08，北京时间）

本次针对 17 项意见逐项核实并修复。代码验收和生产运行分开记录：开发 PostgreSQL 已迁移，未启动常驻 API / worker，未启用生产告警。历史 W8–W10 报告是当时版本的记录，不代表已包含此次修改。

## 逐项结果

| 项目 | 本次结果 | 边界 |
|---|---|---|
| 1 提取临时错误 | 429、5xx、超时、网络错误进入指数退避；最后一次才尝试规则回退。没有规则候选则 dead，不将空结果误记成功。成功 payload 记录 extraction_reason / extraction_failure，job 指标可统计回退率 | 非临时响应错误立即回退；配置错误需人工修复 |
| 2 中文关键词 | 0007 迁移提供中文 bigram + ASCII 词的 SQL 函数和 GIN 索引；保留非中文 simple 全文通道 | 字符 n-gram，不是语言学分词；单字和同义改写质量有限，无需安装第三方 PostgreSQL 扩展 |
| 3 纠正原因 | reason 存入不可变版本和审计 metadata，版本 API 返回；最多 512 字符并过敏感检查 | 历史丢失原因无法补回 |
| 4 向量错误 | 版本不存在、400 等永久错误直接 dead；401/403 为 PROVIDER_CONFIGURATION_ERROR；429 等重试并取 Retry-After 与退避的较大值 | 配置告警有原因码、指标和健康状态，外部通知未接入 |
| 5 提取版本 | worker 仅领取自身版本；提供 drain 和旧版本迁移重入队 | 不自动重提已成功事件；迁移不碰运行中租约 |
| 6 队列运维 | tenant 范围 status、死信重入队、旧模型批量向量重建、深度及年龄指标 | 批次 1–1000；status 最多列 100 个死信；需定时采集、逐批处理 |
| 7 版本分页 | 数据库 LIMIT/OFFSET，额外一条判断 next_offset；get 只读当前版本 | 极深 offset 可后续改游标 |
| 8 幂等保留 | 显式记忆命令记录 7 天；访问时清过期键，另有批量清理 CLI，沿用事务锁 | Event 不可变去重保留事件生命周期；未自动安装定时任务 |
| 9 HTTP 复用 | worker 持有共享客户端，注入提取器并在停机时关闭 | 独立调用提取器仍可自持客户端 |
| 10 worker | 提取 worker 原本已有 SIGTERM；向量 worker 补齐。退出前完成当前任务；原子心跳文件、PID/年龄/配置错误健康检查 | 每进程一租户；采用显式租户清单 + supervisor，无自动租户发现 |
| 11 租约 | 校验外部调用总超时 + 5 秒持久化余量严格小于租约；调用使用总时间预算；写入继续受租约 fencing 保护 | 不实现无限长操作续租；数据库拥塞超出租约会失败并等待重新领取 |
| 12 查询向量 | 每进程租户隔离 LRU/TTL 缓存，默认 256 项/60 秒；并发 8；排队 + 调用总预算 3 秒；降级指标 | 不是集群限流或全 API 配额 |
| 13 生命周期 | invalidate、restore、supersede successor_id 与读取生命周期接口；拆分权限；继任者必须可读、有效、同 scope | 只能恢复普通归档；被取代后再归档不能绕过状态恢复；deleted 终态 |
| 14 SDK | 事件批量写入、版本列表、版本/搜索迭代、生命周期方法；SDK 对所有业务 OpenAPI 路由的真实契约测试 | 新 supersede 请求必须传 successor_id |
| 15 观测 | correct/disable 拒绝指标、无 SQL 文本的语句 span、OTLP HTTP 导出、采样、collector 与告警示例 | collector 示例仅 debug 导出；生产存储、看板、通知与 Prometheus 接线未启用 |
| 16 公平评测 | 增加朴素向量 + 生命周期过滤基线、普通案例；标注中文检索集与真实模型提取独立评测 | 小型构造集，不能推断生产质量或融合检索优于过滤向量 |
| 17 敏感检查 | 显式 remember/correct/reason 与 LLM 使用统一政策；扩充身份证、银行卡、常见令牌、私钥、全角和零宽变体 | 保守模式检查，可能误拒且仍可绕过；不等于完整 DLP |

## 运行与迁移

开发数据库仍使用服务器 Docker 的现有 `pgvector/pgvector:pg15`，端口仅 localhost:55432。本次发现容器原已停止，启动后确认 memories / memory_versions 均为 0，先备份到忽略目录 `.local/backups/`，再从 0006 迁移到 **0007_review_hardening**。未在宿主机安装 PostgreSQL。

生产部署前：停止写入/worker、备份、使用迁移身份执行 `uv run alembic upgrade head`，然后用受 RLS 约束的应用角色运行。0007 的索引建立不是 CONCURRENTLY，大表需安排维护窗口。历史审计保留，不改署名与原始验收结论。

新权限：`memory:archive`、`memory:supersede`、`memory:invalidate`、`memory:restore`；删除仍为 `memory:delete`。签发 JWT 和调用 SDK 的服务应一并更新授权，不能给旧 token 默默扩大权限。

显式命令幂等键从首次记录起 7 天有效；未过期同键同参返回持久结果，异参冲突。过期后按新请求处理：remember 可创建新记忆；其他操作重新校验 revision / 状态。事件写入的 immutable 去重不使用此 7 天 TTL。

## 队列操作

以下命令均在已配置的服务器项目虚拟环境中执行，`TENANT_UUID` 为真实租户 ID；数据库凭据通过受保护环境注入。管理 CLI 是可信主机工具，不是对公网暴露的管理 API。

```bash
uv run python -m agent_memory.workers.admin status --tenant-id TENANT_UUID
uv run python -m agent_memory.workers.admin requeue --tenant-id TENANT_UUID --job-type extract_event --limit 100
uv run python -m agent_memory.workers.admin cleanup-idempotency --tenant-id TENANT_UUID --limit 100
```

切换提取模型二选一：

1. 暂停 dispatch；保留旧模型配置，运行 `uv run python -m agent_memory.workers.extraction drain --tenant-id TENANT_UUID --worker-id drain-old`。drain 等待 pending/retry/running 清空并报告 dead 数量；排空不代表 dead 自动成功。处理死信后再换 dispatcher/worker 的模型。
2. 暂停旧 worker 并等正在运行的租约结束，换配置，再执行：

```bash
uv run python -m agent_memory.workers.admin requeue --tenant-id TENANT_UUID --job-type extract_event --old-version llm-extraction-v1:OLD_MODEL --new-version llm-extraction-v1:NEW_MODEL --limit 100
```

反复执行至 changed=0；旧任务保留为 EXTRACTOR_MIGRATED，不再被通用死信重入队；新事件+版本键去重。对 running 任务另等它完成/租约到期后处理，不能认为一次命令已覆盖所有任务。

向量模型切换：新 worker 使用新模型配置，执行：

```bash
uv run python -m agent_memory.workers.admin rebuild-model --tenant-id TENANT_UUID --model OLD_MODEL --key migration-2026-10-08 --limit 100
```

同一操作 key 重复执行至 queued=0；从旧模型的现存向量版本中分页建任务。维度变化必须先按 embedding 迁移方案处理，本命令不自动改 vector 列维度。缺失向量的版本仍可用现有单版本 rebuild。

## 常驻多租户方案与健康检查

采用静态租户清单；每租户各运行 dispatch、extraction、embedding 三个受 systemd 管理的实例。安装位置使用本项目 `.venv`，不把凭据放仓库或 unit 正文。模板见 `deploy/systemd/`，是部署示例，本次没有启用。

每实例独立 env 文件和 worker ID。signal 停止领取新任务，当前事务完成后退出；systemd `TimeoutStopSec=60` 大于默认租约 30 秒。健康探针示例：

```bash
uv run python -m agent_memory.workers.health --tenant-id TENANT_UUID --worker-id extraction-TENANT_UUID --kind extraction --max-age 60
```

默认 `.local/worker-health`；部署可用 MEMORY_WORKER_HEALTH_DIR 指定受保护目录。dispatch 的 worker ID 为 `dispatch`。探针检查最近任务循环、存活 PID 和配置错误；它不是模型端到端就绪保证。数据库不可达使 worker 退出，由 supervisor 重启。

## OTLP 示例

项目 `.venv` 已安装锁定的 OTLP exporter；Docker 已缓存 `otel/opentelemetry-collector-contrib:0.123.0`。示例限制内存 192 MiB、仅 localhost:4318，配置包含 memory_limiter 和 batch。已实际验证 collector 收到 span 和 metrics；验证容器/网络随后移除，镜像保留。

```bash
docker compose -f deploy/observability/compose.yaml up -d
# 应用 / worker 环境：
# MEMORY_TRACE_EXPORTER=otlp
# MEMORY_METRICS_EXPORTER=otlp
# MEMORY_TRACE_SAMPLE_RATIO=0.1
# OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:4318
```

不导出正文、SQL、参数或异常全文。reason 不放 span/log，纠正原因仅在受权限保护的版本与审计。fallback 比例可用 job reason_code=RULE_FALLBACK / RULE_FALLBACK_EXHAUSTED 对成功任务聚合；检索降级统计 query_embedding 的 reason_code。队列快照在 admin status 时记录，需要周期采集。告警示例需接入 Prometheus 后端才能生效，不代表已部署报警。

参考：[HTTPX 超时](https://www.python-httpx.org/advanced/timeouts/)、[OTLP 导出](https://opentelemetry.io/docs/languages/python/exporters/)、[Collector 排错](https://opentelemetry.io/docs/collector/troubleshooting/)。

## 本次验收证据

- 全量 pytest、ruff、strict mypy、foundation 四道门结果记录于 progress；回归覆盖 429→成功、耗尽回退/死信、永久向量错误、Retry-After、租约 fencing、中文 SQL 索引、审计原因、分页、队列批处理、TTL、缓存隔离、SDK 路由契约和 OTLP 实际收包。
- `hardening-baselines-fixture.json`：4 个用例（含普通有效案例、纠正和删除）；无记忆 0/4，朴素向量 2/4，带生命周期过滤的朴素向量 4/4，系统 4/4。说明此集的收益来自生命周期治理，未证明融合优越性。
- `hardening-retrieval-zh.json`：6 条人工构造记忆，8 个查询（7 个正例、1 个无关负例），实际 PostgreSQL 中文关键词通道，无向量模型。正例 Recall@3 / Hit@1 都为 1.0，负例为空。
- `hardening-extraction-real.json`：真实已配置 API key 调用 `doubao-seed-2-0-mini-260428`，12 个构造事件（7 个正例、寒暄负例及 4 个敏感负例）。候选有无和预设关键词覆盖均 12/12；候选 scope 均由服务端保留。这是提取初验，未持久化这些评测候选，关键词覆盖不等于人工质量评分。

待完成：生产 OTLP 存储与通知、监督进程实际部署、自动清理/快照采集计划、大规模真实标注评测及更完整敏感检测。没有把这些待办标为完成。
