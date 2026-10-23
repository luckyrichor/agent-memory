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

## 阶段1第三轮用户修订（优先于此前自动替换标注模型授权）

本轮只处理 agent-memory，不进入阶段2。标注组合冻结 deepseek-v4-pro、mimo-v2.6-flash；故障更换须先说明原因、等负责人确认，并整批重标。裁判允许预检合格后按实际剩余额度自动切换，但一张对比表必须使用同一裁判；切换时整表重判，每条记录模型与返回版本，额度未知不虚构排序。

ECD 不再作为双标抽取金标、无 κ≥0.7 闸门；共同舍弃仅作人工未核验负样本；固定种子另取100–150段供负责人直接标记应记内容。原文仅服务器本地和负责人私有包，不能发群或进Git；不再生成616条仲裁包。当前只要求负责人填 DuLeMon native-reference 的230抽检，其余旧审核暂缓，不催办；ECD小样表预备但不扩大本轮必填范围。人工回填按冻结原生参照算一致率，低于95%仅采用人工确认子集并重算规模。合成集与冻结标注组合不一致时仅提重标方案，不自行重标。详细执行配置 docs/evals/phase1-round3-policy-v1.json。原方案仓库副本是否包含本轮修订须核对，不把旧副本称最新版。

## 阶段1第三轮收尾授权（2026-10-21）

负责人已批准合成时间线用 deepseek-v4-pro 与 mimo-v2.6-flash 整批重标，覆盖此前仅提方案的限制。输入/切分/指标不变；新批次与旧标签完全隔离，遇到额度故障保留未完成状态，不自行换冻结模型。裁判余额排序/冻结等待控制台截图，不为探余额额外调用、不充值或开启后付费。允许跨云运行入口的模拟402整表重判演示；这不是阶段2验收。

随后负责人对本轮合成重标的402明确授权“换模型继续完成”。这只放开本轮合成时间线替代组合，公开中文旧批次不重写；新组合须独立厂商、采样控制与完整预检合格，并整批重标。当前拟定Ark DeepSeek正式版与腾讯HY4，状态/资格以本轮报告为准。涉及新合成批次时腾讯已是标注厂商，正式裁判池一并排除；模拟路由演示不代表正式裁判资格。

## 2026-10-21 最新方案与第三轮后续

最新版用户原件在 docs/plans/2026-10-21-agent-memory-interview-plan.md，完整保留原作者；旧 docs/agent-memory面试级完善方案.md 为历史版本，差异由报告脚本导出。当前执行配置 phase1-round3-policy-v2.json 优先于 v1 的余额截图/排序、全厂商并集排除规则。

裁判按每张表的答题厂商和实际标注厂商独立排除；预检通过且实际调用成功后按明确顺序冻结主备，不查余额。每表至少两个合格备选；不足时如实列缺口，不把同厂商换渠道误称角色独立。主备均须真实人工校准方可发布正式判分，切换整表重判。公开中文标注不变；合成已授权替代组合独立保留。

合成时间线当前只标“流程验证，不作质量证据”，不得以一致率或 κ 证明真实标注质量。中文查询独立统计真人对话衍生、作者模型生成基准、程序合成；不能混入真实中文金标规模。所有旧切分、指标与验收阈值不变。

负责人本轮只填 DuLeMon 原230抽检的实际核对行，其余人工栏留空；只对非空有效人工行按冻结参照计一致率，低于95%仅输出人工确认子集。程序不得自动读取旧 Agent 标签作为人工结果。ECD120审核表逐字节保持，不催办其他暂缓包。阶段1仍未验收，不进入阶段2。

## 2026-10-21 负责人真实回填与独立困难集

真实回填来源 dulemon230-for-agent.csv，已核对行按旧Agent标签选择，非随机；人工与冻结原生参照比较，不用旧Agent结果充人工。空白保持空白，上下界按全表分母计算；低于门槛只导出独立人工确认子集，不覆盖原生标签/切分。补足路径与查询替换先给可审阅方案，待负责人确认。

synthetic-hard-v1 是独立程序构造集合，构造真值不是人工标签，小样对照调用不代表全量双标完成。原时间线与困难集都只作流程验证；ECD表不动。当前裁判策略v3撤下预下线GLM-5V；旧预检通过仅留历史，禁止用旧证据绕过当前撤下名单。主备缺口及人工校准仍须如实报告。阶段1未验收，不进入阶段2。


## 2026-10-21 获批补量与查询启用（后续最新）

最新原件另存 docs/plans/2026-10-21-agent-memory-interview-plan-v2.md，旧版保留。策略v4：真实中文经抽检通过的记忆点下限700、目标1500；独立随机盲抽72，错误最多3。排除以前按旧Agent标签挑选且已人工核对的项；不能用模型补人工。审核八列与原表一致，不透明item_id、source原JSON、人工栏空白；负责人已明确格式并授权真实表直接私发。抽检通过后才增量补量；冻结标注组合失败仍须请求更换授权。

新版查询启用chinese-queries-v2-hard，旧版不可覆盖，新旧不可同集比较。时间推理/知识更新/多会话单列流程验证，不进质量汇总；困难集人工抽检暂缓。裁判至少一个严格合格备选，公开表数量满足不代表校准通过；合成表不足仍报告，不放宽预检或恢复预下线模型。ECD保持、不催办；阶段1未验收。


## 2026-10-21 共同保留池真实回填后的约束

新人工回填来源dulemon72-final.csv，原池独立盲审未过最多错误三条的门槛；不得以人工keep项推定整池通过。只把原ID去重后的具体人工确认项并入human-confirmed-current.json。后处理原型不可用，不能拿高已知错误召回掩盖误伤。原数据已用于规则开发，后续验收须新独立样本；不足不得复用或抽重。

逐字核验规范：所有具体细节与主体关系须有用户本人原话依据，无依据完整候选降级，不从助手自述、问句、否定或别人的事补用户事实。原型输出不是人工标签，不覆盖负责人确认结果。当前过滤方案未批准，增量标注禁止；如需改写冻结候选或改变复核流程，先给新版本与整批范围供负责人确认。阶段1未验收，ECD/困难集暂缓审核不变。

## 负责人批准标注规程v3（最新）

仅修改公开中文冻结模型对的提示词，使用docs/evals/labeling-guide-v3.md及独立证据响应。程序只精确验证source_id、用户角色、原文子串，不能把词法拼接或主观规则当语义证明。229真实人工项固定按会话开发/最终隔离；最终集不反复调提示词。离线未完成或未达门槛禁止整批重标，整批完整后再抽未审72；补量继续等新盲审通过。失败保留台账，不自动换冻结模型。所有报告、审核表、附件发送当前群，不再私发（负责人最新交付偏好）。阶段1仍未验收。

## v3替代组合已获批准（后续最新）

负责人明确“换模型继续”后，DuLeMon v3新批次单独冻结Ark deepseek-v4-pro-ga-260813与TokenHub hy4-preview；见docs/evals/annotation-v3-replacement-freeze.json。原公开中文标签仍留历史，禁止与新批混用。开发/最终切分原样继承，不能因换模型重抽更容易的题。离线通过后整批重标，不只接旧标签尾部。新表裁判排除DeepSeek、腾讯及答题厂商字节，不沿用HY4作裁判。补量仍等新盲审通过，阶段1未验收。

## 负责人新决定：产量指标与701池盲审（最新）

本轮policy为docs/evals/pool-refresh-policy-v1.json：正确项保留率仅报告，不是通过门；既有8/9拦截已获认可，不做新离线验证。只用开发输出与虚构例修订格式，不复用最终集。701池完整新标后独立抽未审且未用于开发/最终的72条，最多3错，未过盲审禁止增量。旧门槛与失败报告留历史。正式finalizer须用真实人工标签投影，黑名单占位值不充人工。Ark上限触发即停止，不自动改限额/计费或换模型；恢复须同提示词同模型。阶段1未验收。

## 模型额度不足自动换型（负责人最新授权）

负责人明确“模型额度不足就换模型，ark不足就用腾讯云的模型”，因此额度/账户用量上限阻塞后不再等待换型确认。先技术预检，额度不足在有界合格候选中自动换；受影响模型侧必须全池新标，旧部分标签留历史，不接尾混用。另一侧完全相同输入/提示词/模型的完整标签可整份校验复用，不重复付费。入口scripts/continue-pool-with-quota-fallback.py；当前策略docs/evals/tokenhub-pool-fallback-policy-v1.json。省略供应商不支持的API JSON模式不等于放宽程序JSON/证据校验；校验器不变。仍禁止修改服务用量上限/计费。新盲审未过不补量，阶段1未验收，所有交付发本群。

## 2026-10-22 长期记忆与时效性筛选（当前）

最新原件 docs/plans/2026-10-22-agent-memory-interview-plan-v3.md（SHA256由交接脚本核对）；旧版不覆盖。阶段1只做长期记忆，短期有效期机制是以后可选项，不提前实现。真实新盲审按69 keep/3 discard核算，以收到的CSV与冻结模板为准，早先“72全部keep”消息已被负责人更正。新增69项与既有人工项按原ID去重；不能把整池称逐条人工确认。

采纳前对原265条及人工正例对照仅新增长期/临时判断，任一方临时即提出剔除，不新增候选。筛选无自行设置的通过线；结果交负责人决定后才采用旧池筛选结果。新增量已获授权采用同样时效性标准，所有引用校验维持原样；新增池须再次独立72盲审通过才计规模。额度不足允许技术合格备选替换，受影响一侧整批重标，不混用部分标签；报告实际标注厂商对裁判排除的影响。只在本群交付，阶段1仍未验收，ECD表不动。

## 时效性增量固定批与格式拒绝（2026-10-22后续）

增量以固定100段为独立批，首批完成前已冻结此执行范围。额度换型重标当前批受影响模型侧全部输入；已完成批保留完整来源，不拼接当前半批，报告各批实际厂商并按对比表实际数据排除裁判。原始响应结构/引用不合格的条目程序拒绝为uncertain，不修复字段、不降低原精确引用标准；程序uncertain不得当模型语义标签计算一致率。缓存只重放真实响应并重验，不把历史usage当新调用。

ECD新人工回填已获授权接入，仅方法哈希指标公开；来源必须称AI草稿加人工确认，不能称独立人工。旧ECD120模板仍保留不改。旧265池时效性采纳继续等负责人决定；新补量独立盲审未通过前不能计入可靠规模。当前阶段1仍未验收。

## 单条请求恢复（2026-10-22最新）

多候选腾讯Turbo实际根结构失败不等于额度耗尽。虚构全格式预检与真实分组控制均独立保存；当前V5入口/scripts客户端v3对该型号每请求一条，原提示词、候选、严格结构/引用校验不改，不修补原响应。排查真实ID见.local/phase1/round3/temporal-v1/transport-probe-excluded-ids.json，须排除后续盲审及可采纳池。旧失败快照留历史，不把它冒称当前运行状态；所有状态以increment-current.json及实际进程/台账为准。新增目标未完成时阶段性72包只本地准备，不发负责人催审；完整补量后再交新增独立盲审。所有交付仍只本群，ECD原文不公开，阶段1未验收。

## 当前运行已因真实402关闭（2026-10-22最后状态）

V5单条调用修复了格式问题，但随后当前腾讯侧也返回402；运行已结束，increment-current.json指向当前冻结尝试，报告仍phase1_accepted=false。未完成当前批不入金标，已完成候选未盲审不采纳；目标未完成的阶段性72表仅本地准备，不发催审。不是全目录余额结论，剩余额度没有查询。后续恢复应新建独立尝试，保留失败台账，复用同模型同输入真实响应；若换型则当前受影响侧整批重标。不得直接重跑已标失败ledger、删除失败记录、放宽结构/引用标准或开通计费。当前真实状态与细计数见closeout-status.json及交接报告，所有交付仍只本群。

## 负责人旧池采纳与新增账户（2026-10-22最新）

按docs/evals/phase1-new-accounts-policy-v1.json执行。旧未审池仅扣人工已知错误，时效性筛选保留参考不用于剔除；与逐条人工正例按原ID去重后作为补量基数。新增池仍执行临时不得keep，补量完成且独立盲审通过前不计可靠规模。新账户预检须真实完成，旧账户成功不代替新预检；目录可读不代表模型可调用。未完成批index4两侧整体作废，新账户客户端v4只允许本轮范围真实响应缓存，禁止重放旧单侧。后续额度换型仍整侧重标，完整历史批保留来源。新取样与盲审种子独立，排除全部历史审核、开发、最终及技术调试项；ECD保持原样。所有交付发当前群，阶段1仍未验收。


## 阶段1已验收、阶段2 B0获准（2026-10-23最新）

负责人已明确验收阶段1并启动阶段2，见docs/evals/phase1-acceptance-current.json与b0-policy-v1.json。B0标签不可覆盖，只加载其冻结业务源码；框架可新增，不优化系统。所有指标仅开发集，测试集保留最终一次性运行。校准300表人工栏空白、隐藏裁判结果、仅服务器私有，交负责人后暂停；未校准分数不正式发布。运行时抽取/向量化额度不足暂停，不自动换型；其他角色切换须整表或整组，独立厂商要求不变。压测待独立跨地域Linux固定IP机器，说明见docs/baselines/b0/load-generator-preparation.md。三类构造题只作流程验证，不混质量总分；不进入阶段3。


## 负责人同系列续跑授权（北京时间2026-10-24，覆盖此前换型号整组重跑）

消息om_x100b628d31ba14a0df2cc7d1869eac1明确允许同系列模型额度切换后继续。当前policy-v5/sample-v8，保留并验证完成的会话组合与逐题答题判分检查点，实际型号/Key代号/原始调用/父哈希留痕；版本混用不称精确单型号实验。不同系列仍整组重跑；向量化不同模型/提供方/协议不混用旧向量空间。预检、厂商独立、人工校准、仅开发集与阶段2范围不变。300人工表仍导出后暂停，不代判、不进阶段3。
