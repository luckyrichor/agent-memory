# AGENTS.md

最后更新：2026-10-08（北京时间）

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

### 基线状态（2026-09-20 在 tx 上完整验证）

| 门 | 结果 |
|---|---|
| `uv run pytest` | **103 passed**（含 Testcontainers 测试；2026-09-19 基线为 75） |
| `uv run ruff check src tests migrations` | All checks passed |
| `uv run mypy src`（strict） | 47 文件无错 |
| `evals.foundation_runner` | 8/8，0 租户泄漏，0 删除命中 |
| `alembic upgrade head` | 三条迁移全部成功 |

这是**完整**基线，不是「除了需要 Docker 的部分」。已验证的包括：RLS 跨租户隔离（已知 ID 攻击）、迁移建表与 pgvector 扩展、Postgres 仓储与内存仓储行为一致、Event 摄取的原子性与幂等、Outbox 派发幂等、Job 租约防抢占与过期恢复、API 的 JWT 租户绑定与版本生命周期、Event→Evidence→MemoryVersion 完整血缘。

**在此基础上改动后，四道门都要重新跑过再提交。**

**测试必须跑全量，不能只跑改动相关的那几个文件。** M1 期间踩到过一次：单文件跑通、全量跑挂，原因是 alembic 迁移会影响 logging 状态，而单跑时迁移根本没执行。

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

`observability/` 是**叶子包**：不 import 其他层（只 import `config`），所以每层都能用它而不产生环。日志、span、指标三条通路共用同一份字段白名单。理由见 `docs/design-decisions.md` 的 D1、D2。

`infrastructure/in_memory*.py` 与 `repositories.py` / `event_repositories.py` 是同一批 Protocol 的两套实现 —— 这是单测和 evals 能秒跑、只有集成测试才需要 Docker 的原因。**加新用例时先在 `application/*_ports.py` 定义 Protocol，两套适配器都要实现**，否则 evals 会掉队。

## 核心不变量（改代码时不能破坏）

- **租户身份只来自 JWT**。请求体里出现 `tenant_id` 一律拒绝。API 连接**不得**使用数据库 owner，因为 owner 绕过 RLS；迁移里建了 `agent_memory_app` 角色（`NOSUPERUSER NOBYPASSRLS`）。
- **PostgreSQL 强制 RLS**：每张表 `ENABLE` + `FORCE ROW LEVEL SECURITY`。
- **记忆版本不可覆盖**。纠正走 `POST /versions` 追加新版本，`expected_revision` 做乐观并发。删除是逻辑删除；状态机 8 态，`deleted` 是终态。
- **Event 不可变**，`(tenant_id, idempotency_key)` 幂等；同键不同内容、或同 session 重复 sequence，都返回稳定 409。
- **Event 与 Outbox 同事务落库**，再由 dispatcher 幂等转 Job。Job 30 秒租约、指数退避上限 300 秒、5 次后进 `dead`。
- **候选记忆不得扩大 scope**：`ExtractionWorker` 显式检查 `candidate.scope != event.draft.scope` 并判为不可重试失败。
- **日志和 CLI 输出不得包含 Event 正文或记忆正文**，只输出计数、ID、结果和原因码。这条已经由 `observability/fields.py` 的字段白名单强制：白名单里没有任何能放正文的字段名，越界即抛 `UnsafeTelemetryField`。**要加新字段就改那个文件**，不要绕过 `StructuredLogger` 直接用 `logging`。
- 高风险组合（procedural + tenant scope + 无 `memory:admin`）自动落到 `needs_review` 而非 `active`。

## 已实现 vs 未实现

**不要把未实现的说成已完成**，README「当前边界」一节是权威口径。

已有 —— 可观测性地基、三类记忆、四类 scope、JWT + 权限 + RLS、幂等创建、乐观并发、不可覆盖版本、生命周期、审计、embedding worker、三路混合检索与分页、Event/Outbox/Job/Evidence 链路。M4 的 API/融合/模型配置和验收边界见 docs/retrieval.md；真实模型5条语义改写验收已通过；生产规模质量评估未做。

未有 —— 见下方路线。

## 开发路线（Phase 3–5）

设计依据是 `docs/superpowers/specs/2026-08-30-enterprise-agent-memory-system-design.md`，改架构前先读第 19 节阶段划分和第 20 节的 10 条验收标准。

**第一梯队**（岗位 01 直接考 + 被 `agent-ops-platform` 依赖）

- **混合检索**：PG 全文 + pgvector 向量 + 结构化过滤三路候选，可解释融合与重排。含 **embedding worker**（M3 已有生成/落库/重建/重试管道，真实模型语义改写初验通过，生产规模质量评估未做）。
- **Context Builder + Token 预算**：M6已实现API/SDK与可测试预算裁剪，保守UTF8计数及证据/冲突边界见docs/context-builder.md。
- **可观测性**：M1 已完成地基 —— 全链路 trace、JSON 结构化日志、四个基础指标（2026-09-20）。**未完成**：没接任何后端（只有 console 导出器，无 OTLP／采样／告警／看板），spec 第 17 节的四层评测仍然全空。
- **基线对比评测**：spec 验收标准第 10 条要求对比 No Memory 和 Naive Vector 两条基线，未实现。
- **Python SDK**：M2 已实现 HTTP SDK；`agent-ops-platform` 要调用本服务。

- **真实 LLM 提取器**：现在的 `CodingFailureRuleExtractor` 只认 build/test 失败这一种硬编码规则。**2026-09-22 已从第二梯队提为 M7，排在 W8**（须早于 M5 基线评测，否则评测量的是临时替身）。

**第二梯队** —— 生命周期补全（supersede/archive 已实现，物理删除执行仍未做）、Consolidation Engine、MemoryRelation（spec 8.5 列了但表未建）、Feedback Service、评测扩容（现在只有 8 场景 1 条 golden）、限流。

### 已知缺口与它们的归属

外部评审 2026-09-22 提的五点已逐条核实属实，处置写在 `workplan-docs/总节奏表.md` 第五节，**权威口径是 README「已知缺口」那张表**。要点：CI 在 W4 接、删除幂等与防绕过测试进 M2、分页随 M4、LLM 提取器是 M7；**物理删除执行与限流明确暂不排期，不得声称已支持**。

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


## 2026-10-01 当前执行入口

M2/M3 与 W4 CI 的最新实际验收见 docs/progress.md（历史 103 tests 基线不可当本次结果）。`bash scripts/check.sh` 使用锁文件运行 pytest、ruff、mypy strict、foundation_runner；当前 shell 缺 docker 组时按环境记录使用 `sg docker -c 'bash scripts/check.sh'`。embedding 操作与夹具/真实 provider 边界见 docs/embedding-worker.md；生产迁移须另行核对部署数据库，当前本次只迁移 Testcontainers。

## 2026-10-07状态补充

M7真实LLM候选提炼与M5三组基线工程初验通过。真实模型、敏感检查边界及样本限制见docs/llm-extraction-and-baselines.md；四道门139测试通过。M6现已完成，见docs/context-builder.md；未新增常驻服务。


## 2026-10-08 评审后状态补充

历史说明保留为当时记录。当前能力和边界以 README 与 docs/review-hardening-2026-10-08.md 为准：提取临时故障先重试；显式命令幂等保留 7 天；0007 提供中文 bigram、纠正 reason、successor 关系；队列 admin 和共享 HTTP、查询缓存、OTLP/采样已实现。生产常驻服务与报警仍未部署。新生命周期权限必须单独授予，supersede 必须传 successor_id；版本历史必须 SQL 分页，不退回全量读取。


## 第二轮评审当前约束（2026-10-08）

当前细节见 docs/review-followup-2026-10-08.md：invalidated/superseded 只能继续 deleted，不准经 archive 绕过；中文 bigram OR 排序，不代表同义语义；ContentRejected 使用固定规则码，API 保留原错误码并附 reason_code，SDK 同步；异常向量第三次失败 dead，缓存先于 semaphore 检查。四道门 208 测试通过，旧报告是历史证据。


## 2026-10-19 用户新方案与阶段闸门

用户原件docs/agent-memory面试级完善方案.md已原样保存，优先按其任务卡推进；不自行改指标、切分、阈值。每阶段交付代码、报告、命令、环境指纹与遗留，负责人确认验收才进入下一阶段（方案§13.5）。本轮阶段0只修错/核实；B0标签是修复后源码，阶段2全指标报告仍待后续。开发记录docs/devlog/每任务一份，数字引用自动生成报告，署名如实保留Codex、具体模型版本未核实；不声称用户写代码或已经独立复核。

PG租约以数据库clock_timestamp为准，拿锁后再读时间，不用应用now或事务起点now判租约；内存适配器可注入时钟仅用于测试。HTTP支持conversation.message（user/assistant + bounded summary），仍是不可信事件，scope/JWT/RLS/提取验证保持。升级需要0008迁移；有对话历史时禁止有损降级，不为过测试删除生产数据。

整体HTTP正文默认1MiB，实际流量累计后才解析；超限413。版本offset上限10000，搜索offset2900等边界不取消。pip-audit使用冻结锁文件导出版本，原始前后扫描保留；不把一次0已知公告说成完全无漏洞。下游agent-ops-platform仍固定1e2730c，联调迁移源码须取其对应干净checkout，不自动升级其SDK pin。

## 2026-10-19 用户更新：持续推进

用户明确要求“持续进行直到完成，或者遇到需要我决定的再停下来问；每个阶段都要有交付报告”。此授权覆盖前述例行逐阶段确认暂停约定：技术闸门通过并交付报告后直接进入下一阶段，不再仅因未收到例行阶段验收回复而停工。仍不得改变指标/切分/阈值；真正需要负责人决策、人工标注/仲裁、缺少账号授权或不可达的数据才集中提问；等待期间继续独立工作。阶段0报告里的“例行等待验收”是当时状态，后续以本条用户新授权为准。

## 2026-10-19 后续用户修订：只交付阶段1

用户随后明确改为按阶段完成，本轮仅开发阶段1，交付后等待确认，不进入阶段2。共享TokenHub凭据已由/home/ubuntu/AGENTS.md授权，使用with-tencent按需注入，不再要求用户复制密钥；凭据存在与模型真实预检通过分别记录。负责人仲裁和盲审仍需真实人工完成，禁止助手代签。

## 2026-10-19 用户更新：耗尽后切换可用模型

用户授权免费试用耗尽时尝试其他可用模型，不因单个模型402停止；不授权充值或开启后付费。替代模型先验证可访问性与评测预检，保持双标注厂商独立、裁判角色独立，并记录具体模型/提示词/请求配置。不同模型的部分标签保留为独立实验，不静默拼成同一冻结模型结果。阶段范围仍仅阶段1。Ark旧版Pro访问失败与账户额度分开核查，不由404推断全部Ark模型不可用。

## 2026-10-19 用户确认Ark新版

用户明确“改用新版doubao-seed-2-1-pro-260915”。阶段1及后续获授权评测的抽取/对话、答题使用该ID，角色配置docs/evals/model-roles-v2.json。通过with-ark与scripts/with-phase1-runtime.py只注入目标子进程的新版抽取配置，不改共享密钥、无关服务、历史报告、B0标签或原始用户方案。完整预检与任务校准仍必须分别完成。向量配置不随对话模型改变。

## 2026-10-19 采样策略纠错（优先于此前模型候选记录）

原方案§7明确排除采样固定的Kimi，现官方Kimi-K3指南仍写固定温度且不可关思考。先前仅凭100格式/5次一致就把Kimi视为合格是执行错误，已停止；该模型的历史部分标签只留作探索，不进入正式数据/裁判/盲审。诊断可保留，但预检必须同时满足格式、一致性及模型参数资格；API接受字段不等于字段生效。当前角色以model-roles-v3.json为准，v2保留历史但不再使用其Kimi角色。公开中文第二标注候选改为文档支持温度0、关闭思考的deepseek-v4-pro-0813，先完整预检；合成集仍DeepSeek4.1+MiniMax2.7，裁判候选GLM；公开中文GLM+新DeepSeek时裁判候选MiniMax，厂商逐数据集独立。禁止为省额度放松这些要求。

## 2026-10-19 负责人确认盲审阈值

用户已明确回复“盲审95%”：负责人10%盲审一致率须≥0.95，模型间κ≥0.7不变。冻结配置docs/evals/human-review-policy-v1.json。阈值批准不等于批准任何实际标签或阶段验收，不代签；历史报告中的“阈值待确认”是当时状态，后续按本条执行。

## 2026-10-20 本轮仅真实中文补量

本轮只处理阶段1真实中文缺口，具体约束见docs/evals/chinese-expansion-policy-v1.json。标注模型按最新用户指令固定deepseek-v4-pro-0813、minimax-m2.7；此条优先于此前“额度耗尽自动换模型”的泛化授权，更换前必须说明理由并等待负责人确认。语料原生参照不以模型保留票筛掉，仍须真实人工抽检；PerLTQA为作者模型生成并修订的基准，不计真实中文规模。ECD大小/CRC要核对，源语料和审核原文仅本地，对外只有清单哈希、方法指标。冻结来源会话切分继承，不改指标/阈值，不代人工审核，不进入阶段2。实际响应违背关闭思考设置时拒绝接收，不能仅凭参数被接受或旧预检通过认定当前合格。

## 2026-10-20 后续授权：模型故障自动替换

用户随后明确“换模型继续，以后遇到类似的问题都这样做”。覆盖上一条逐次更换需确认的限制：额度耗尽、接口不可用或采样控制不生效时，自动挑选其他独立厂商模型；先核对文档并预检，合格后冻结新组合、对当前固定数据完整双标，保留旧实验与用量，不跨模型拼标签。不降低指标/阈值，不改切分/标注指南，不充值或开后付费，不代替负责人审核。新模型及切换原因写入版本化配置和交接报告；常规模型替换不再重复请求许可。仍仅阶段1，真正缺少凭据、所有合格可用模型耗尽或需修改既定标准时才问负责人。
