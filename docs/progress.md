# 进展记录

## 2026-10-20 阶段1真实中文补量与完整重标（Codex）

完整双标、开发集指南验证、替代模型预检及审核包更新已完成；ECD一致性仍未达标，人工审核未回填，阶段1未验收、不进入阶段2。数字和具体边界见 [自动报告](reports/phase1-chinese-guide-v2-full-2026-10-20/delivery.md) 与 [开发记录](devlog/phase1-chinese-guide-v2-2026-10-20.md)。

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


## 2026-10-08：17 项外部评审修复

详见 [逐项结果与运维说明](review-hardening-2026-10-08.md)。修改涉及提取重试/回退、中文 bigram 索引、纠正原因、向量错误分类、队列运维、SQL 分页、7 天幂等保留、共享客户端、健康检查/超时预算、查询缓存、生命周期权限/继任关系、SDK、OTLP 与独立评测。SIGTERM 提取 worker 原已有，本次补齐向量 worker。

- 本地全量 `uv run pytest -q`：**182 passed in 11.00s**；ruff、strict mypy（66 文件）通过；foundation **8/8**，tenant leaks=0、deleted hits=0。
- 真实 key 调用 doubao-seed-2-0-mini-260428，12 个构造事件的候选有无及关键词覆盖 12/12；不是生产质量评分。
- 公平向量基线：朴素 2/4，增加生命周期过滤 4/4，系统 4/4；尚无融合优于过滤向量的证据。
- 实际 PostgreSQL 中文关键词评测：7 正例 Recall@3/Hit@1=1.0，1 负例为空；6 条人工构造记忆，不包含向量语义质量。
- OTLP 本地 HTTP 测试与 Docker collector 实际收包通过；临时 collector 已移除，镜像缓存保留，未启用生产报警。
- Docker 开发 PostgreSQL 原先停止；启动后确认 memories/versions 均为空，先 pg_dump 到忽略的 .local/backups，再迁移至 0007_review_hardening。未安装宿主机 PostgreSQL，未启动常驻 API/worker。
- 本次结果对应此次修改后的代码。后续提交及 GitHub CI 状态应以实际提交记录为准，不能沿用旧 W10/ZIP 的验收哈希。


## 2026-10-08：数字 UUID 敏感误判修复（Codex）

基线 6684532 + 本轮修改。排查 agent-ops-platform 偶发写入 422 时，确定性复现旧数字正则把 UUID `12345678-1234-4234-8123-123456789012` 中 `12345678-1234-4234` 当作银行卡片段。旧失败未保留正文，无法还原其实际随机 ID；此机制已独立复现，能解释相同的 422 故障。

仅在手机号/身份证/银行卡的数字检查中排除完整、独立的 canonical UUID；密钥关键词、常见令牌、邮箱等仍检查原全文。非法 UUID、附加令牌前缀以及 UUID 旁真实卡号/手机号仍拒绝。增加 10 个针对用例。四道门：**192 passed in 10.88s**、ruff 通过、strict mypy **66 文件**、foundation **8/8**，零租户泄漏/删除命中。精确源码 SHA256 与修复前合成证据见 measurements/content-policy-uuid-2026-10-08.json。无数据库迁移、无模型调用或常驻服务变更；ops 集成使用固定数字 UUID 防止回归。


## 2026-10-08：第二轮五项记忆评审修复（Codex）

基线 bb09ed0 + 本轮修改；精确源码与测试 SHA256 见 measurements/review-followup-source-2026-10-08.json。先复现 invalidated 允许 archive、中文改写在旧 AND 查询中无候选两项失败，再修复。失效/被取代只允许删除，中文 OR 候选排序，英文敏感术语按边界与赋值检测并提供 API/SDK reason_code，异常向量最多两次重试，缓存命中绕过并发排队。旧归档前状态不可反推、长数字仍保守拦截。

最终四道门：**208 passed in 11.47s**、ruff 通过、strict mypy **66 文件**、foundation **8/8**，零租户泄漏/删除命中。扩展中文构造集：13 查询（12 正例+1负例），正例 Recall@3/Hit@1=1.0、负例为空；不外推通用语义质量。无真实模型调用、无迁移或服务部署。详见 review-followup-2026-10-08.md。

## 2026-10-13 M6 Context Builder（Codex）

来源 870afeb + 本轮修改；实现API/SDK和独立预算构建器，212测试、ruff、strict mypy67文件、foundation8/8通过。完整JSON包装计预算、UTF8保守单位、版本引用、按价值裁剪、跨租户/workspace/删除隔离均有测试。初次全量211通过/1失败为SDK路由覆盖漏调用，补测试后全量通过；边界见context-builder.md。

## 2026-10-19 面试级完善方案阶段0（Codex）

用户原件80744字节原样入docs/agent-memory面试级完善方案.md，保留@sh6_apple署名；任务按§2阶段0与§13逐阶段交接执行。源码固定1e9d6f3，报告脚本在该干净提交运行，源文件/测试/迁移/锁文件散列已回查。每任务开发记录见docs/devlog/INDEX.md；报告、环境、命令、漏洞扫描原件在docs/reports/phase0-2026-10-19。

修InvalidScope为422/INVALID_SCOPE；foundation逐case捕普通异常并继续，不吞取消。核实原HTTP只收tool.result，新增conversation.message的user/assistant受限summary与0008约束迁移，真实API验收幂等/scope隔离，拒绝有数据时有损downgrade。租约原用应用now，PG现以clock_timestamp筛选并拿锁后重新读wall clock；renew/succeed/fail和队列ready调度对齐DB时间；内存与domain单测仍可注入时钟。整体HTTP正文有界缓冲，检查声明长度和实际流量，补版本offset/key/workspace等边界及深嵌套早停。

初始212测试通过。修复后首次全量232通过/1失败，原因旧迁移测试在共享库回滚碰到有对话数据保护；保留安全拒绝，迁移roundtrip改独立容器并新增有数据降级拒绝覆盖。PG旧过期测试不再靠应用未来时间造过期，改临时库期限/ready字段；领域测试不变。最终自动报告234通过0skip、ruff、strict mypy68文件、foundation8/8/0泄漏/0删除命中。指纹PG16/pgvector0.8.6、0008、仍无ANN索引；只用临时库，未动持久业务数据或常驻部署。

冻结锁文件all-groups导出后pip-audit扫描，前19报告项（18去重公告，3个包），后56个本机有效依赖0已知公告。PyJWT2.13.0→2.15.1、urllib32.7.0→2.8.0，开发pytest8.4.2→9.1.1/pytest-asyncio0.26.0→1.4.0；升级后的四门通过。保留原始JSON与工具版本，不等同未知漏洞/跨平台安全保证。Ruff最初指出DB时钟类型错误宜抛TypeError，统一helper后通过。没有安排真实模型评测调用。

下游ops SDK仍固定1e2730c，不擅自改pin；用对应干净worktree复验真实memory联调用例1通过，ops README同步说明迁移来源匹配。B0只冻结修复后运行源码；阶段2全指标报告尚未做。负责人验收和独立复核抽查尚未完成，按方案§13.5停在阶段0交接，不进入阶段1。


## 2026-10-19 阶段1开发与首批交接

最新用户范围仅阶段1，结束交付后等确认。新增评测计算/单测、单入口实验、公开数据归一化、来源映射与受限血缘观察、模型预检/标注/本地重放/盲审材料。

公开数据已下载并记录哈希，具体数量和模型预检结果以阶段1报告为准；所有统计来自实测，不以模型目录注册当作实验通过。原始语料与标签留.local。

已出现并修复/保留的失败：全量pytest测试模块同名冲突；模型高频429；MiniMax格式不足99%；测试固定提取器遗漏领域必填字段及枚举拼写。Ark方案指定对话模型与带版本ID均返回404，实际可用ID待负责人提供，不擅自换模型。阶段1未正式验收，没有进入阶段2。

公开中文真实标注中另遇MiniMax未转义引号与TokenHub HTTP402。保留错误与部分标签，后续模型调用已暂停，等待负责人检查账户状态；不自动充值、不替换模型。


## 2026-10-19 14:55–14:56（北京时间）模型最小请求复测

按用户要求，对TokenHub deepseek-v4.1-flash、Ark doubao-seed-2-0-pro及doubao-seed-2-0-pro-260215各做两次最小JSON请求。共6次，未恢复批量标注。TokenHub两次均HTTP402，具体错误码401008，明确说明“免费试用额度已耗尽且未启用后付费”；此前“余额/配额可能有问题”的不确定解释由此收敛为该服务返回的具体计费配置原因。需要负责人决定是否开通后付费，该操作会产生后续计费，不由助手自行开启。Ark四次均HTTP404/InvalidEndpointOrModel.NotFound，响应只给出模型/接入点不存在或无访问权限，不能单凭404断言已下线或未开通。

脱敏证据：docs/reports/phase1-2026-10-19/model-retest-2026-10-19.json；原始安全响应摘要及prompt哈希保留.local/model-retests/20261019T065550Z。无业务代码变更，不重复跑四道门。阶段1仍未验收。

## 2026-10-19 可用模型轮换与Ark版本调查（Codex）

后续用户授权耗尽后尝试其他可用模型，覆盖前面的“暂停等待账户处理”。TokenHub MiniMax-M3、GLM-5.2、HY3最小调用均200；已恢复阶段1标注，仍不自动充值或开后付费。新增HY3/GLM标注参数和保留无效缓存的显式重试，四门307 tests、ruff、strict mypy78文件、foundation8/8通过（源码ef30c03）。细节和脱敏实测摘要见docs/devlog/2026-10-19-P1-05-模型替代与Ark排查.md及model-alternatives报告。

Ark同一共享密钥调用新版Pro260915和Mini260428成功，旧Pro260215仍404；官方旧Pro于9月24停止新购、11月24正式下线，当前尚未EOS。旧版访问权限/开通及项目归属需控制台确认，有额度不等于指定旧版可调用。未擅自替换方案指定Ark角色或升级部署；已询问是否采用新版并做完整预检。阶段1尚未通过人工闸门，未进入阶段2。

## 2026-10-19 用户批准新版Ark，完成真实预检

用户确认“改用新版doubao-seed-2-1-pro-260915”，已提供阶段1显式runtime profile及子进程注入入口，保留旧报告/原始方案/B0。新Ark、Kimi-K3、MiniMax-M2.7完整预检摘要在阶段1报告目录；新Ark实际LLMExtractor合成角色请求200、LLM_EXTRACTED、scope正确、4.36秒，不等于抽取质量测量。原语料/调用结果只留.local；密钥不落盘。

公开中文GLM完整标签1648条生成；MiniMax-M2.7公开批次出现schema失败和120秒ReadTimeout，保留失败/未知用量后改Kimi完整独立重跑，试批50条有效。合成集沿用MiniMax-M2.7继续与已完整DeepSeek配对。不同数据集裁判需与本数据集标注厂商独立，角色分别冻结，人工校准仍待完成。阶段1未验收，不进入阶段2。

## 2026-10-19 Kimi资格纠错（撤回此前角色资格结论）

回查原方案§7及腾讯云当前Kimi指南，Kimi-K3温度固定、不能关闭思考。此前把“100格式+5次一致”当完整资格的判断有误：API接受temperature=0/thinking.disabled不证明生效。已停止Kimi并将全部Kimi部分标签排除于正式标注/盲审/一致性结果；历史原件不删改。原preflight摘要保留为当时机械预检记录，资格审计model-eligibility-audit-v1.json明确role_eligible=false。当前模型角色用v3，v2保留历史。

修复预检资格闸门与标注入口，新增回归：即便Kimi全部格式/一致性通过，仍不能通过固定采样策略；不允许其发起正式标注。314 tests通过（15.91s）、ruff、strict mypy78文件、foundation8/8。合成集1630双标注完整仍有效：DeepSeek4.1与MiniMax2.7 κ=0.9292432354，18分歧、163盲审；人工字段全空，未验收。公开中文GLM1648完整标签仍有效，第二份将由符合参数要求的新候选模型完整生成，不拼接Kimi部分结果。已开始deepseek-v4-pro-0813完整预检，官方TokenHub DeepSeek指南支持温度0及关闭思考，使用不同于已耗尽4.1Flash的服务ID。

## 2026-10-19 双标注完成与负责人交接

最终正式配对均完整：合成1630条（DeepSeek4.1+MiniMax2.7），公开中文1648条（GLM5.2+DeepSeek-V4-Pro-0813）。模型κ与人工材料数量由脚本生成，见docs/reports/phase1-model-rotation-2026-10-19：合成κ0.929、18分歧/163盲审；公开κ0.848、114分歧/165盲审。Kimi数据全部排除，未修改阈值以掩盖错误。负责人已确认盲审95%，冻结human-review-policy-v1.json。

报告源db3f264（当时干净），验证原件对应随后固化的a2a8422源码；当前src/tests/migrations/uv.lock与该测试版本相同。319 tests通过，ruff、strict mypy79文件、foundation8/8。模型预检/角色连通不代表生产质量或阶段通过。

已准备带空人工字段的CSV/JSONL审核包，负责人真实回填尚未收到。真实中文抽取金标准规模不足：公开中文两模型共同保留511条，候选1648不能当作金标准数量；仍需人工校准后补充样本。中文查询/题型覆盖、自然负样本和裁判人工校准未通过，均未以本次候选标注冒充完成。阶段1保持未验收，阶段2未开始。接收器会核对源/标签/记录散列、完整ID和真实人工回答，先评分再改正；不代签。
# 2026-10-20 阶段1真实中文补量

已实现来源补量、旧候选原因诊断及原生参照审核工具。指定模型因额度及关闭思考行为受阻，正式双标未完成；完整数据计数、审核规模与验证结果见 [自动生成的交接报告](reports/phase1-chinese-expansion-2026-10-20/delivery.md)。人工回填、负样本对话比例、裁判校准和查询覆盖仍未验收，不进入阶段2。

## 阶段1第三轮交接（2026-10-21）

源码 `e70cb00c2fa2703527e31db7a5e133291161f5f3`：全量 345 tests passed（16.85s），ruff、mypy strict、foundation通过；具体日志/哈希见 `docs/reports/phase1-round3-2026-10-21/`。ECD按负责人修订改作暂定负样本与人工小样，不再受其旧κ闸门卡住；共同舍弃候选 2104、全候选共同舍弃会话 251，均人工未核验。种子42私有小样 120 会话，按个人信息线索分层；新包仅要求原生DuLeMon 230 当前必填，其余旧审核暂缓。模板二次生成逐件SHA256一致，人工字段仍全空，私有包只发给负责人私聊，不发群。

标注模型/厂商与确切组合已代码冻结，旧自动双标入口不再处理ECD；更换须负责人先确认并整批重标。裁判整表切换与低于95%时仅采用人工确认子集已实现；真实API合成小样加明确故障注入验证整表重判，不冒充真实额度用尽或阶段2结果。GLM5.2等旧服务本轮实际复测仍402（免费包耗尽、后付费关闭）。GLM5v首次一次超时失败，完整重测通过；角色模型技术格式通过仍不冒充已核实的思考开关资格；合格通用候选 2，主加备选所需 3 尚未满足。调用API/模型清单未暴露余量，故未伪造额度排名或主裁判冻结。群历史读取尝试被机器人权限230027拒绝，仓库方案仍是旧ECD口径，按本轮明确消息执行并等待最新版原件。

时间线旧组合与当前冻结组合不符，已核对旧标签/台账哈希并给出整批重标方案，未自行重标。LongMemEval与LoCoMo实际临时PG/RLS/API检索已运行，开发子集召回和范围写入交接；不当作全量质量或阶段2。期间预算脚本曾因Unicode行分隔符误用splitlines解析失败，改为逐物理JSONL行流式读取，未改源数据/切分。旧指标、指南、阈值原件未改；阶段1未验收，未进入阶段2。

## 火山 Ark 裁判补查（2026-10-21）

按负责人要求扩大到Ark推理Key；glm-5-2-260617完整预检 100/100，正式裁判提示五次一致。合并腾讯历史证据共 3 个合格渠道/模型候选；GLM5.3虽可调用，因官方不支持关闭思考仍排除。额度管理接口拒绝推理Key，需AK/SK签名，数字余额/排序/预算充足性仍未核实。详见 docs/reports/phase1-round3-ark-2026-10-21/。未更换标注模型，未启动阶段2；当前CLI的跨云正式路由尚未集成，不把本次查询当生产池切换验收。

## 阶段1第三轮收尾（2026-10-21）

源码 db349e6（检索运行的相关源文件逐一SHA匹配）。LoCoMo同题同源：2/152 → 98/152，实际SQL定位英文全词AND导致无词法候选，映射与导入核验无缺陷；朴素BM25在同题上对照。LongMemEval-S固定开发 50 题，RT1@10 44/47；策略拒绝块有台账，全部题目分母保留。GLM-5V本轮完整复测通过，格式100/100。跨云运行入口模拟402整表重判通过，不消耗真实裁判额度。
负责人明确批准模型替换后，新合成组合deepseek-v4-pro-ga-260813 + hy4-preview各重标1630条，κ=1.0，旧标签不混用，人工未确认。公开中文组合保持。腾讯作为新合成标注厂商被正式裁判排除；余额排序/冻结继续等截图。全量352测试/17.56s与四门通过。阶段1未验收、不进阶段2。报告：docs/reports/phase1-round3-closeout-2026-10-21/。


## 2026-10-21 阶段1第三轮后续（Codex）

最新用户原件已完整读取并归档 docs/plans/，保留旧版本与原作者署名。裁判按数据表角色选择，取消余额门；人工校准仍必须。公开池预检选择已冻结，合成池缺合格备选，未冒称全部完成。中文查询构建、合成一致性泄漏审计、部分人工回填接收器已交付；数据量与题型、模型失败/实测用量、完整验证结果统一引用[自动交接报告](reports/phase1-round3-followup-2026-10-21/delivery.md)。合成批次只作流程验证，ECD表与指标/切分保持；人工未代填。阶段1仍未验收，不进入阶段2。


## 负责人回填与独立困难集（Codex，北京时间2026-10-21）

核验负责人附件与冻结原表，按已核对行计算一致率与全表上下界，因未达门槛独立输出人工确认子集。已解释按旧Agent标签选择的偏差；补足路径与查询替换仅提案。独立构建困难集、完整复现哈希，并用已有合成模型组合做小规模打乱/遮蔽/反事实实测，不覆盖原时间线。重新查询两渠道，仍有稳定裁判备选缺口；v3策略撤下GLM-5V且正式入口防止旧证据绕过。真实数据、用量、规模与完整验证结果见[脚本生成报告](reports/phase1-round3-owner-hardset-2026-10-21/delivery.md)。阶段1未验收、不进入阶段2；ECD保持。

执行返工：初次诊断用了不存在的python命令，改用uv run python；困难集初次ruff报dict写法，修正后通过。补充私有正例子集导出后重新跑完整四门，未用局部测试代替。


## 获批补量路径、八列盲审与查询启用（Codex，北京时间2026-10-21）

完整重读新附件并归档v2原件，保留旧版和署名，差异及内部旧文冲突均列报告。按负责人新门槛创建v4策略；真实盲审表按最终指定的八列生成、人工栏空白，来源JSON不变，已私发。初次虚构格式预览被负责人否决后已替换；首次本地模板记录哈希含自身的兼容问题已修正并经接收器验证，错误稿未作为正式表交付。

启用新查询注册表及常规评分数据转换入口，流程题型从质量汇总和配对质量差异中排除。至少一个裁判备选门槛已接入运行入口；合成表仍无合格稳定备选，保留失败台账。增量补量依赖真实盲审通过，未提前执行。全量四门、规模、版本与用量均引用[脚本生成报告](reports/phase1-round3-approved-followup-2026-10-21/delivery.md)。阶段1未验收，ECD/困难集人工暂缓。


## 共同保留池抽检失败与逐字过滤实验（Codex，北京时间2026-10-21）

真实回填通过冻结字段/完整覆盖校验，原共同池未达既定错误条数门槛，仅独立合并负责人确认正例。按原ID去重，未将整池采纳。错误按负责人理由分互斥主因及可重叠细节标签。

已设计细节与本人原话核验规程，记录严格对齐、细节片段和子句隔离等试验；当前原型拦截已知错误但误伤极高，明确未通过。过滤后未审项不足新的独立盲审数量，因此新表未生成；没有抽重、复用开发样本或新标注补数。当前输入已用于调试，不再作为独立通过证据。ECD及已启用查询、指标定义保持。

全部计数、置信区间、失败结果与完整四门见[自动交接报告](reports/phase1-round3-verbatim-filter-2026-10-21/delivery.md)。未开始增量标注，阶段1未验收。下一步证据对齐/新候选版本路径作为待确认提案，未改冻结候选。

## 负责人批准标注规程v3与离线额度阻塞（Codex，北京时间2026-10-22）

按负责人新授权新增提示词与逐细节原话响应，保留冻结公开中文模型对及全部原候选。程序只精确核对source_id、user角色和连续子串；语义支持与细节完整性不能由引用机械检查证明，必须保留新的人工盲审闸门。固定会话隔离开发/最终切分及提示词哈希在调用前冻结，本轮未调最终集，未使用人工答案作为模型输入。

实际开发首批两模型均HTTP402，服务明确免费额度耗尽且未开通后付费；当即停止，无重试、替换、充值或后付费开通。离线指标全部未验证，不以缺失结果当成功拦截；最终集未调用，整批重标、新盲审、增量补量均未启动。先前批准的是执行路径，不代表效果已经通过。当前外部阻塞需同模型额度恢复，或负责人另行明确决定替换模型，不能自动绕过冻结。

完整检查结果、划分分母、当前人工规模、失败码、SHA及未完成项见[脚本生成报告](reports/phase1-round3-evidence-v3-2026-10-22/delivery.md)。阶段1未验收，ECD与困难集审核暂缓保持。后续附件与报告只发当前群，不再私发。此次无测试返工；新增单元测试覆盖额度阻塞不触碰最终集/整批入口，原文精确匹配与语义不可证明边界。

本轮文档检查返工：报告生成脚本发现行尾空白，已清理；不涉及冻结提示词、源数据或模型实验，未重复发起调用。

## v3获批替代组合与真实离线失败（Codex，北京时间2026-10-22）

负责人明确授权换模型继续后，独立冻结Ark DeepSeek版本与TokenHub HY4新组合。旧公开中文标签与失败批次只留历史，原始候选/来源和提示词不改；原开发/最终切分逐字继承，不重新抽题。历史同模型完整预检证据、本轮实际可调用性与v3格式检查均留台账，未用余额推断能否调用。

两模型完成整套真实离线验证，全部HTTP成功；效果仍未达人工正确项保留参考线。已如实报告已知错误拦截、两个正确子集保留及旧表discard拦截，并区分模型本身拒绝与引用契约失败。引用子串真实仍不能保证模型枚举完整或语义成立；未采用放宽/绕过引用规则的做法。最终集已运行，不反复用其调提示词。

因离线失败，整批重标、新独立盲审与增量补量均未启动。下一步提案只允许开发部分改进，需独立新人工验证来源才能再取得通过证据，不催ECD/困难集。当前真实中文人工规模未增加，阶段1仍未验收。新标注厂商含腾讯，旧公开表HY4裁判备选不能用于新表，缺口未掩盖。所有计数、token、哈希、完整四门与详细分组见[自动交接报告](reports/phase1-round3-evidence-v3-replacement-2026-10-22/delivery.md)。所有交付只发当前群。

## 取消产量门槛、701池格式重标与服务上限阻塞（Codex，北京时间2026-10-22）

负责人批准保留率只报告、接受历史错误拦截结果、不做新离线评价，并收窄重标范围。使用开发输出诊断发现旧示例关系数组为空；完全虚构新结构示例修正，候选和精确校验器不变。中间格式版遗漏原reason枚举，首批失败已留台账；恢复枚举后全池独立新批重跑，未混用部分标签。原最终原始响应不用于修订，701中的历史已用候选可以按授权重标但不得进入新盲审。

当前HY4完成整池，DeepSeek遇到SetLimitExceeded服务暂停，停止后未重试、修改安全用量上限、充值/开通后付费或换模型。双标不完整，未生成盲表；仅完整覆盖后用真实人工标签投影及全部历史ID再排除的finalizer可抽表。恢复入口只显式处理同提示词同模型剩余候选，不覆盖失败台账。黑名单占位索引不当人工结果。

完成只读DuLeMon可用对话与候选槽位盘点，保留原内部切分，不增量取样；区分实际单模型产量、未知联合产量及条件补量/调用量估算，未以估算填实际规模。裁判按新表厂商排除腾讯、DeepSeek与字节，技术主候选与正式校准状态分开，备选缺口未掩盖。

全部计数、估算公式、实际用量、失败响应哈希与完整四门见[脚本生成报告](reports/phase1-round3-pool-refresh-v3-2026-10-22/delivery.md)。阶段1未验收，盲审未过不增量，ECD/困难集审核保持。此次检查返工含初次工具脚本文本解析失败（未执行命令）、测试导入格式修复；实际源文件与日志均留对应版本。报告和后续附件只发当前群。

## 腾讯替代完整重标与新独立盲审交付（Codex，北京时间2026-10-22）

负责人授权额度不足自动换型后，检查当前腾讯目录与候选真实可调用性。发现部分Flash拒绝可选response_format模式，省略该模式后实际可用；程序严格JSON、用户角色和原文子串校验不变，未把兼容问题冒称额度问题。新型号通过既定控制/格式资格检查与虚构v3格式检查，没有重复负责人旧最终题作离线质量评价。

受影响侧对完整冻结池重新标注，旧Ark部分标签不混入；HY4的同池同提示词完整结果经SHA与覆盖校验整份复用，未重复计费。新双标及联合产量均完成，按新固定种子抽取独立未审条目，原八列、原JSON来源、人工栏空白、编号不透明，已发当前群。条目与既往人工/开发/最终无重叠，来源会话重叠另报。未把候选计入真实人工规模，盲审未回填前不增量。

可用对话库存不变，补量调用预算根据本次真实池留存给出带明确分布/精度假设的敏感性估算；正式裁判池仍缺稳定备选与人工校准，不因标注完成掩盖。全部数字、实际调用、哈希、测试与未完成项见[自动交接报告](reports/phase1-round3-tokenhub-pool-2026-10-22/delivery.md)。

返工：适配器漏导入read_rows，首次单测与虚构响应汇总发现异常；修复后复用已合格缓存，无额外模型请求，并留修改前代码/清单SHA及完整失败日志。增加带斜线型号别名的额度错误识别回归，最后完整重跑四门。没有降低引用标准、修改计费/服务上限。最新自动换型授权及整池规则已写AGENTS与策略；阶段1未验收。
