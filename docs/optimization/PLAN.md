# agent-memory 优化任务与交接文档（阶段 3–6）

> 这份文档是**活文档**：做优化的人（Claude、Codex 或其他 agent）开工前先读完它，收工前更新第 8 节"状态与交接日志"。
> 做完后给负责人的面试故事线写在同目录 `STORY.md`（第 10 节说明）。

- 创建：2026-11-02　分支：`optimize/stage3-6`
- 上游依据：`docs/plans/2026-10-22-agent-memory-interview-plan-v3.md`（方案原件，不改）、`docs/baselines/b0/`（B0 基线材料）
- 本文档和方案原件冲突时：**方案原件的指标、切分、阈值不改**；本文档只决定"怎么做优化"。

---

## 1. 读这份文档的人需要知道什么

### 1.1 项目一句话
Python / FastAPI / PostgreSQL + pgvector 的跨会话 Agent 记忆服务。写入路径：`事件 → outbox → job → 抽取 worker → 候选记忆 → embedding job → 向量`；读取路径：`查询 → (词法 + 向量 + 结构化) 三路候选 → RRF 融合 → context 打包`。

### 1.2 优化的目的（面试叙事的骨架）
先量出现状（B0 基线），再针对量出来的问题逐项优化，每项优化都有"改前 / 改后"的数据。**没有测量依据的优化不做，做了没有数据的优化不写进"提升"里。**

### 1.3 B0 基线里已知的问题（这些是优化的靶子）
| 来源 | 问题 |
|---|---|
| 仓库内 `docs/reports/phase2-b0-pause-2026-10-24/` 和 `docs/baselines/b0/` | 旧 B0 重做过程的暂停记录、预检、预算 |
| **Agent 汇报，仓库里没有原始文件**（B0@1e9d6f3 重做，配置 `B0-deepseek-v4-pro-kinfra-20261026-v1`） | ① 抽取候选永远不会变成 `active`，全链路检索为 0（缺陷编号 `B0-CANDIDATE-ACTIVATION-MISSING`）；② 搜索/上下文接口 1 QPS 起大量超时（1 万规模 64% 错误，10 万规模 98%，p95≈30s）；③ F2 连接耗尽后约 30 秒才返回 500；④ F9 磁盘满时错误语义不对；⑤ SC4 日志泄露查询文本 117 次；⑥ LC7 逻辑删除后正文版本仍在；⑦ 抽取精确率 48.8%（21/43）、召回 23.3%（7/30）、F1 0.316；ECD 负样本误抽 37 条 |

> ⚠ 第二行的数字来自负责人转交的 Agent 报告，**Agent 的 B0 报告和数据没有推送到 GitHub**。引用这些数字时必须标注"Agent 汇报"，在原始文件入库前不得当作仓库内证据。B0 的 DeepSeek 同时是金标准标注者之一，抽取指标可能偏高，所有报告必须披露。

---

## 2. 工作约束（必须遵守）

1. **没有任何模型 / 向量 API 密钥**。密钥不得出现在聊天、日志、报告、Git、命令参数里。因此：真实模型评测（E1 答题准确率、抽取精确率/召回、判分）**本环境做不了**，只能做不依赖真实模型的验证（单测、本地 Postgres 集成测试、夹具向量的微基准）。
2. **不得声称"质量提升"**，除非有开发集上的前后对比。本环境产出的是"行为正确性"和"系统性能（延迟/吞吐/调用次数）"证据；质量提升留给负责人侧用真实 B0 配置重跑后确认（第 9 节）。
3. **测试集（test split）只在最后统一评估一次**，优化过程只用开发集。
4. **不放松任何验收闸门**：四道门（pytest / ruff / mypy strict / foundation_runner）每次提交前全量跑。
5. **压测数字的口径**：本环境的压测是"同一台机器上的客户端 + 服务 + 数据库"，只能说明改动的**相对**效果，不能当作方案要求的"独立压测机、跨地域"正式压测结果。每条数字必须标注环境。
6. 日志、CLI 输出、报告里**不得出现事件正文或记忆正文**（见 `AGENTS.md` 核心不变量）。
7. 新增指引只写进 `AGENTS.md`，不写 `CLAUDE.md`（见 `CLAUDE.md` 的规定）。

## 3. 环境怎么搭（本沙箱，无 Docker）

```bash
uv sync --all-groups --frozen            # Python 3.12 环境
# 无 Docker 时用系统 PostgreSQL 16 + pgvector 0.6.0 代替 Testcontainers：
#   scripts/dev/localpg.py 是 pytest 插件，把 PostgresContainer 换成临时本地集群
PYTHONPATH=scripts/dev .venv/bin/python -m pytest -p localpg -q
```

- 正式环境（负责人的 tx 服务器）仍用 Docker，`pgvector/pgvector:pg16` 镜像里的 pgvector 版本比本沙箱新（≥0.8），支持迭代扫描；**本沙箱的向量索引实验只能验证 0.6.0 的行为**，结论里必须标注。
- 基线（改动前，本沙箱）：453 passed、1 failed。唯一失败的 `test_b0_harness::test_unfiltered_baseline_and_worker_pipeline_offline` 是子进程内直接找 Docker，属环境问题。

## 4. 任务总表

状态：`待做` / `进行中` / `完成` / `完成-仅单测` / `放弃(原因)`。"证据"列填文件路径或提交号，不填则不算完成。

### A. 功能缺口（阶段 3 的前置）

| ID | 任务 | 方案编号 | 状态 | 验证方式 | 证据 |
|---|---|---|---|---|---|
| A1 | 候选记忆激活：抽取结果按策略进入 `active` 或 `needs_review`；新增 confirm / reject 公开接口与权限 | B0 缺陷、阶段 3 前置 | 完成 | 单测 + Postgres 集成测试 + 端到端（事件→可检索） | `tests/integration/test_candidate_activation.py`、`tests/unit/domain/test_activation.py` |

### B. 读路径性能（O1、O2、F2）

| ID | 任务 | 方案编号 | 状态 | 验证方式 | 证据 |
|---|---|---|---|---|---|
| B1 | 两段式检索：先只取 id 与分数，只对当前页取正文；候选数上限可配置（默认 1000→200） | O1 | 完成-传输量降低，延迟无改善；默认值未降 | 单测 + 微基准（行数/传输量/延迟） | `tests/unit/application/test_retrieval.py`、`tests/integration/test_two_stage_retrieval.py`、`scripts/bench/retrieval_read_path.py`、`measurements/b1-{before,after}-10k-*.json` |
| B2 | 英文词法通道补 GIN 索引；检查三路查询的执行计划 | O1 | 完成-改用存储列（GIN 在 RLS 下用不上）；仅 1 万行 | `EXPLAIN` 前后对比 | `migrations/versions/0010_stored_lexical_vectors.py`、`scripts/bench/explain_read_path.py`、`measurements/b2-*` |
| B3 | 向量近似索引（HNSW）实验 + 过滤后结果过少的处理 | O2 | 完成-不上索引迁移；改查询形状后即使无索引也快约 2 倍；索引改为运维可选步骤 | 召回率对精确扫描、延迟；8 千 / 2 万向量 × 候选上限 1000 / 100 | `src/agent_memory/infrastructure/retrieval.py`、`scripts/bench/vector_index.py`、`measurements/b3-nearest-first-{8000,20000}-{1000,100}.json` |
| B4 | 连接池参数可配置、池耗尽快速失败返回 503（带 Retry-After），不再挂 30 秒 | F2 | 完成-行为已验证，未做压测 | 单测 + 并发复现 | `tests/integration/test_pool_exhaustion.py`、`api/infrastructure_errors.py` |

### C. 写路径与 worker（O4、O5）

| ID | 任务 | 方案编号 | 状态 | 验证方式 | 证据 |
|---|---|---|---|---|---|
| C1 | worker 有活时不睡眠，只有空闲才等待 | O5 | 完成 | 积压 N 条任务的清空时间 | `docs/optimization/measurements/c-*-burst-*.json` |
| C2 | 触发式唤醒：PostgreSQL `LISTEN/NOTIFY`，保留低频轮询兜底 | O5 | 完成 | "写入→可检索"延迟 p50/p95 前后对比 | `c-*-steady-*.json`、迁移 `0009_job_notify.py`、`tests/integration/test_worker_wakeup.py` |
| C3 | 单进程多并发消费（`--concurrency`） | O5 | 完成 | 吞吐对比；租约不重复领取 | `docs/optimization/measurements/c3-conc{1,4}-burst-*.json`、`tests/integration/test_worker_concurrency.py` |
| C4 | 任务优先级（交互写入 > 批量导入） | O5 | 完成-交互事件 p50 29.7 s → 0.22 s（1500 条积压，前后范围互不重叠） | 混合负载下交互任务延迟，优先级 on/off 各 3 次 | `migrations/versions/0013_job_priority.py`、`tests/integration/test_job_priority.py`、`scripts/bench/job_priority.py`、`measurements/c4-priority-{off,on}-{1,2,3}.json` |
| C5 | 同租户、同模型、相同正文的向量复用（内容哈希） | O4 | 完成-仅单测/集成测试（计数提供器断言调用次数，无规模化测量） | 向量调用次数前后对比（计数提供器） | `tests/unit/application/test_embedding_reuse.py`、迁移 `0011_content_hash_index` |

### D. 可靠性与安全（阶段 6 能在本环境验证的部分）

| ID | 任务 | 方案编号 | 状态 | 验证方式 | 证据 |
|---|---|---|---|---|---|
| D1 | 查询文本不进日志 / span（SC4） | SC4 | 完成-守卫测试；当前代码未发现泄漏点 | 捕获日志的断言测试 | `tests/integration/test_query_text_not_logged.py` |
| D2 | 磁盘满 / 数据库不可用等错误映射为明确的 503 与稳定错误码（F9） | F9 | 完成-仅单测（模拟 SQLSTATE），没有真的写满磁盘 | 单测（模拟异常） | `tests/unit/api/test_infrastructure_errors.py` |
| D3 | 逻辑删除后的正文清理方案（LC7）：设计 + 可执行的清理命令 | LC7 | 完成-手动命令，无自动调度；范围见日志 | 集成测试（清理后正文与向量不可读） | `src/agent_memory/infrastructure/purge.py`、`workers/purge.py`、`tests/integration/test_purge_deleted.py` |

### E. 记忆深度与上下文（阶段 4、5）

| ID | 任务 | 方案编号 | 状态 | 验证方式 | 证据 |
|---|---|---|---|---|---|
| E1 | 证据引用：检索结果和 context 里带上来源事件的引用 | 阶段 4 | 完成-仅规则抽取产生的证据；每次搜索多约 1.6–3 ms | API 测试 | `tests/integration/test_evidence_refs.py`、`tests/unit/application/test_retrieval.py`、`test_context_builder.py`、`measurements/e1-{before,after}-10k-*.json` |
| E2 | 精确重复去重：同租户同作用域内规范化后相同的候选，不新建记忆，只追加证据 | 阶段 4 / LC1 | 完成-仅抽取路径；并发竞态未处理（见日志） | 单测 + 集成测试 | `domain/dedup.py`、迁移 `0012_dedup_hash`、`tests/integration/test_candidate_dedup.py`、`tests/unit/domain/test_dedup.py`、`tests/integration/test_dedup_migration.py` |
| E3 | 上下文打分：相关度 + 新旧（按记忆类型分半衰期）+ 来源可信度，按 分数/占用 贪心装入预算 | O6 | 完成-机制与确定性已验证；权重只是起点值，未在开发集上选 | 单测（三因子各自能改变顺序、确定性）+ 集成（真库元数据、跨租户） | `src/agent_memory/application/context_scoring.py`、`tests/unit/application/test_context_scoring.py`、`tests/integration/test_context_metadata.py` |
| E4 | 冲突标注：同主体同类型相互矛盾的记忆在 context 里标 `conflicts` | 阶段 4 / O8 | 完成-只有词面重叠规则，标 `similar_text`；语义冲突未做 | 仅规则型（不调模型）；语义冲突留给后续 | `src/agent_memory/application/conflicts.py`、`tests/unit/application/test_conflicts.py`、`tests/integration/test_context_metadata.py` |

### F. 本环境做不了、需要负责人侧完成

| 事项 | 为什么做不了 | 需要什么 |
|---|---|---|
| 用真实 B0 配置重跑开发集，比较优化前后的质量指标 | 没有模型 / 向量 API 密钥 | 负责人让 Agent 用同一配置（`B0-deepseek-v4-pro-kinfra-20261026-v1`）在优化分支上重跑 |
| 正式压测（独立压测机、开环固定速率、p95/p99） | 没有独立机器，本环境客户端与服务同机 | 按 `docs/baselines/b0/load-generator-preparation.md` 在压测机上跑 |
| O10 向量模型对比 | Ark 额度用尽，腾讯额度未知 | 仅腾讯内部 0.6b 对 4b 可选 |
| 测试集最终评估 | 约定只在最后跑一次 | 阶段 5 收尾时由负责人批准 |

## 5. 设计要点（每项一两段，细节在代码和测试里）

### A1 候选激活
- 现状：`PostgresExtractionBackend.commit_candidates` 写入 `status=candidate`，领域状态机里 `candidate` 只能转 `deleted`，没有任何公开路径变成 `active`；检索只看 `active`，所以全链路检索恒为 0。
- 方案：新增激活策略 `MEMORY_CANDIDATE_ACTIVATION=auto|manual`。`auto` 时，低风险候选直接 `active`，高风险（租户作用域的流程性记忆，沿用显式写入的 `_activation_status` 规则）进 `needs_review`；`manual` 时全部留在 `candidate` 等人确认。新增 `POST /v1/memories/{id}/confirm` 与 `/reject`，权限 `memory:review`，状态机补 `candidate/needs_review → active/rejected`。
- 安全边界不变：候选不得扩大作用域；审核只改状态，不改内容。
- **需要负责人确认的决定**：默认值取 `auto`（让全链路开箱可用）还是 `manual`（更保守）。当前先按 `auto` 实现并在日志里记下，负责人可改默认值。

### B1 两段式检索
- 现状：词法、向量、结构化三条查询各最多取 1000 行，**每行都带完整正文**；融合后只用前 `limit` 条。绝大部分传输和反序列化是浪费。
- 方案：三个通道只返回 `memory_id, version_id, score`，融合排序后只对当前页（≤100 条）一次性取正文。保持对外响应字段不变。
- 候选上限改成配置项，评估默认值对召回的影响；**不在没有召回数据的情况下盲目降**。

### B3 向量索引（HNSW）
- 现状：`memory_embeddings` 没有向量索引，检索是精确扫描 + 过滤。
- 难点：近似索引先找"全局最近的 N 个"再过滤租户 / 状态，小租户可能被挤到只剩几条甚至 0 条。
- 方案：实验对比 ① 无索引精确扫描 ② 全局 HNSW + 放大候选 ③ 小租户走精确扫描、大租户走索引。
- **结论（实测，tx 服务器 Docker `pgvector/pgvector:pg16`，pgvector 0.8.6，客户端与库同机）**：
  - 候选上限取生产默认 1000 时，**规划器从不选 HNSW 索引**——8 千行和 2 万行都一样，建了索引也不选。加索引对当前查询毫无作用，`0014_vector_hnsw_index` 迁移已删除。
  - 真正起效的是**查询形状**：先在 `memory_embeddings` 上取最近邻（物化 CTE），再关联 `memories` 过滤状态，而不是先 join 再整体排序。即使**没有索引**，8 千行 126.8 → 61.5 ms，2 万行 239.2 → 111.7 ms，约 2 倍；召回@20 全为 1.0（新形状返回的仍是那批最近邻，只是不再重复扫描）。小租户（500 行）11.3 → 11.2 ms，没有退化。
  - 只有把候选上限压到 100，索引才会被选中：原始两步 SQL 14.5–18.0 ms，但召回掉到 0.4983（`ef_search=40` 且无迭代扫描时**候选只剩 23 条**）到 0.7967；开迭代扫描后 `ef=40` 恢复到 0.7650。这条路径是拿召回换延迟，**不适合默认开启**。
- 决定：上"最近邻优先"的形状，不上索引迁移。索引写成运维可选步骤，前置条件是 pgvector ≥ 0.8（`hnsw.iterative_scan`），因为低于 0.8 时过滤会把近似扫描截断成几十条，正是上面 0.4983 那种召回塌陷。
- 诚实边界：夹具是聚类合成向量（50 个中心 + 噪声 0.3），**不是语义向量**，召回数字只说明形状与索引的行为，不能当检索质量；规模只到 2 万，没有 10 万；客户端与数据库同机。

### E4 冲突标注
- **不做语义判断**。规则是结构性的：同一主体、同一记忆类型、用词高度重叠（`lexical_tokens` 的 Jaccard ≥ `MEMORY_CONTEXT_CONFLICT_SIMILARITY`，默认 0.6）但正文不同，就互相标 `{"memory_id", "reason": "similar_text"}`。这正是"同一字段被改了口"的形状，也同样是"无害改写"的形状，所以字段里写的是 `similar_text`，不是"矛盾"。
- 为什么不用证据表里的 `contradicts`：写路径只产生 `triggered_by` 与 `supports`，没有任何生产者写 `contradicts`，只按这个角色标就是一个永不触发的功能。已记录的 contradiction 仍然会进 prompt（E1 把 role 放进 `evidence_refs`），E4 补的只是"跨记忆配对"。
- 渲染：`conflicts` 从占位的 `"not_assessed"` 变成列表，空列表表示"查过了，没有"。指向未装进预算的条目的引用会被剪掉——留一个读者无法解析的 id 比承认这份 context 是局部的更糟。
- 局限（写进代码注释里，别在汇报时忘掉）：① 短句失效——"我住北京" 与 "我搬到上海" 几乎没有共同 bigram，标不出来。② 语义冲突无解，需要模型，超出本任务范围。③ 措辞相近但其实相容的两条会被误标；这个字段只是给读者的提示，**不修改存储**。
### C2 触发式唤醒
- 数据库在 `jobs` / `outbox_messages` 插入时 `pg_notify`；worker 用独立连接 `LISTEN`，收到通知立刻领取；`poll-seconds` 保留作兜底（通知丢失、连接断开时不卡死）。租约、围栏、`FOR UPDATE SKIP LOCKED` 不变。
- 注意：通知只是"叫醒"，任务是否可领仍由数据库里的状态和租约决定，所以通知重复或丢失都不影响正确性。

### C4 任务优先级
- 现状：`jobs` 只有 `available_at` / `created_at` 排序，领取是纯 FIFO。批量导入一灌，交互写入排在几千条后面。
- 方案：`jobs.priority`（`BULK=0` / `INTERACTIVE=100`）+ 索引 `ix_jobs_claim_order(tenant_id, job_type, priority DESC, available_at, created_at, job_id)`；领取时按 `priority DESC` 再按原来的顺序，所以**同优先级内部仍是 FIFO**，默认值 0 与改动前行为等价。
- 优先级要跨两跳传递：outbox 消息带 `priority` → `extract_event` 任务继承 → 抽取事务里设 GUC `app.job_priority`，让触发器生成的 `embed_memory` 任务继承。只改第一跳的话，交互事件仍会卡在别人的 embedding 任务后面。
- 边界：outbox → job 这一跳仍按到达顺序派发（`dispatch_once` 不分优先级）。它只搬运下游引用、不干活，排队时间近似为零；真要改，代价是 outbox 表也要加列。

### C5 向量复用
- 只复用**完全相同**的正文，键是 `(租户, 模型, 正文 SHA-256)`，**不跨租户**。近似重复不在这里处理（归 E2 以及后续语义去重）。

### E3 上下文打分
`总分 = w相关 × 相关度 + w新旧 × 新旧度 + w可信 × 可信度`，三项先归一到 0–1；新旧度 = 0.5^(年龄/半衰期)，半衰期按记忆类型区分；可信度按 `authority_level` 分档。装入时按 `分数 ÷ 占用` 贪心，相关度低于门槛的不装。权重默认值只是起点，**必须在开发集上选**，本环境只验证机制。

- 实现（`application/context_scoring.py`，纯函数、可单测）：相关度 = 本页融合分 ÷ 本页最高分；新旧度 = 0.5^(年龄/半衰期)，半衰期 episodic/semantic/procedural = 14/180/365 天；可信度 = `authority_level` ÷ 5（`ENTERPRISE_POLICY`）。默认权重 1.0 / 0.3 / 0.3，相关度门槛 0（默认不丢任何条目）。
- 为什么相关度按**本页**归一：RRF 分数没有绝对量纲（取决于几个通道命中），任何"绝对阈值"都只是个看起来有道理的数字。
- 为什么按 `分数 ÷ 占用` 而不是单纯按分数：预算是稀缺资源，"短且几乎同样相关"比"长且略好一点"更值。
- 元数据走**页级一次查询**（`CandidateProvider.facts()`），只取类型、版本创建时间、`authority_level`、作用域主体；没有创建时间的条目按中性 0.5 计，不因缺字段被丢。
- context 路由改为与 `/v1/memories/search` 走同一条检索路径并直接读真实 page。原先它把 `SearchHit` 重新拼成 `RetrievalHit`，正好会丢掉 E3 要用的元数据。
- 局限：权重与半衰期**没有**在开发集上选过，也没有证据说明新顺序对读 prompt 的模型更好；没有真实向量，测不出检索质量差异。

## 6. 度量方法

- 本地微基准脚本放在 `scripts/bench/`，输出 JSON 到 `docs/optimization/measurements/`，每个文件头部记录：提交号、数据规模、机器（核数/内存）、PostgreSQL 与 pgvector 版本、是否同机客户端。
- 对比必须成对：同一脚本、同一数据、同一机器，改前后各跑 ≥3 次，报告中位数和范围。
- 夹具向量（`FixtureEmbeddingProvider`）只用来测系统路径，**不代表语义质量**。

## 7. 验收门

每个任务提交前：
1. `uv run pytest`（全量，含集成）；本沙箱用 `-p localpg`。
2. `uv run ruff check src tests migrations`
3. `uv run mypy src`（strict）
4. `uv run python -m agent_memory.evals.foundation_runner`
5. 新增行为必须有对应测试；性能类改动必须有 `docs/optimization/measurements/` 下的前后数据。

## 8. 状态与交接日志（只追加，不改历史条目）

### 2026-11-02 — 启动
- 做了：拉取仓库（本地原落后远端 8 个提交，已快进到 `53cba0f`）；搭环境；跑基线（453 passed / 1 环境失败；ruff、mypy strict 通过）；读完检索、写入、worker、状态机代码；确认发现点如下。
- 代码事实（改之前）：
  1. 候选只能转 `deleted`，无任何激活路径。
  2. 检索三通道各取 ≤1000 行且带正文；英文词法通道没有对应索引（现有 GIN 只覆盖 `simple` 配置和中文 bigram）；没有向量索引。
  3. 三个 worker 都是"处理完一条就睡 2 秒"，不管队列里还有没有活；抽取 worker 和 embedding worker 一次只处理一条，并且 worker 进程**按租户**启动。
  4. 抽取候选的 `confidence` 固定为 0.5、`authority_level` 为 `AGENT_INFERENCE`，所以基于置信度的自动激活没有意义，激活策略要显式配置。
  5. `ContextBuilder` 里 `evidence_refs` 恒为空、`conflicts` 恒为 `not_assessed`（占位符，E1/E4 填充）。
- 下一步：A1 → C1/C2/C3 → B1/B2/B4 → B3 → C5/D1/D2 → E 系列。

### 2026-11-02 — A1 完成
- 做了：`domain/activation.py`（初始状态策略）；`Memory.review()`（candidate/needs_review → active/rejected）；`ExplicitMemoryService.review()` 与 `review_queue()`；路由 `GET /v1/memories/review-queue`、`POST /v1/memories/{id}/confirm|reject`；SDK 同步（仓库有"SDK 覆盖全部路由"的测试，必须同步）；配置 `MEMORY_CANDIDATE_ACTIVATION`（默认 `auto`）；抽取 worker 入口接上配置。
- 验证：全量 463 passed（本沙箱 localpg，不含需要子进程 Docker 的 `test_b0_harness`）；ruff、mypy strict、foundation 8/8。
- 踩坑记录：① 两个旧测试（`test_automatic_memory_pipeline`、`test_llm_pipeline`）原本断言抽取后状态是 `candidate`，现改为显式传 `activation="manual"` 保留其原意，**不是**放松断言；② JWT 的工作区声明字段是 `allowed_workspace_ids`，不是 `workspace_ids`；③ 集成测试里 `NOW` 必须取过去的时间，否则任务 `available_at` 在数据库时钟之后，worker 领不到；④ 同一租户下多个测试共用库，检索类断言要用互不重叠的词表。
- 局限：评审队列的作用域过滤是取页后再过滤，权限窄的审核人可能看到不满的页；量大后要下推 SQL。
- 下一步：C1 → C2 → C3，先建"写入到可检索"的延迟测量脚本（改前先测）。

### 2026-11-02 — C1/C2/C3 代码完成，数据已测（同机、夹具向量，非真实模型）
- 做了：`workers/loop.py`（有活不睡、LISTEN/NOTIFY 唤醒、轮询兜底）；迁移 `0009_job_notify`（jobs / outbox 插入时 `pg_notify`，载荷是 `md5(tenant_id)`，不含租户 ID 和任何正文）；三个 worker 入口改用共享循环；新增 `--no-notify`、`--concurrency`、embedding 的 `--poll-seconds`、`--fixture-latency-ms`（测试用，模拟慢提供器）；抽取 worker 每个并发循环各建一个 extractor（LLMExtractor 带 `last_reason` 状态，并发共享会串）。
- 测量（`scripts/bench/pipeline_latency.py`，各 3 次，本沙箱 2 核、同机、规则抽取 + 夹具向量，所以只反映排队和轮询开销）：
  - 稳态（每 1.5 秒一条，共 20 条），向量就绪 p50：改前 7.4–7.8 s，p95 11.4–11.9 s；改后 0.06 s，p95 0.08–0.09 s。
  - 突发（一次 40 条），全部向量就绪耗时：改前 81 s（= 40 条 × 2 s 睡眠），改后 1.2 s。
  - 改前"稳态"其实已经积压：到达速率 0.67 条/s 超过每阶段 0.5 条/s 的处理上限。
- 未完成：并发 1 对 4 在 300 ms 模拟延迟下的吞吐对比被中断，没有数据，不得写成已测；全量测试在最后一次改动（`--fixture-latency-ms`）之后尚未重跑。
- 下一步：重跑全量四道门；补并发对比；然后 B1/B2/B4。

### 2026-11-02 — C3 补测完成，四道门重跑通过（新会话接手）
- 环境：新沙箱没有 pgvector，用 `apt-get install postgresql-16-pgvector` 装上（0.6.0，与此前一致）；`uv sync --all-groups --frozen` 后按第 3 节方式跑。
- 四道门（本沙箱 localpg，非 Docker）：pytest 476 passed（排除需要子进程 Docker 的 `test_b0_harness`）；ruff 通过；mypy strict 102 文件无错；foundation 8/8。这是 `--fixture-latency-ms` 改动之后第一次全量重跑。
- C3 吞吐对比（`scripts/bench/pipeline_latency.py`，突发 40 条，embedding 夹具模拟 300 ms 延迟，各 3 次，2 核同机、规则抽取）：全部向量就绪耗时，并发 1 为 13.36–13.48 s（中位 13.45 s），并发 4 为 3.78–3.99 s（中位 3.97 s），约 3.4 倍。数据在 `measurements/c3-conc{1,4}-burst-*.json`。这只说明"慢提供器下并发能把等待重叠起来"，不代表真实模型的吞吐。
- 新增 `tests/integration/test_worker_concurrency.py`：24 个任务、4 个并发循环，断言每个任务恰好被领取一次且多个循环都分到了活。
- 下一步：B1 → B2 → B4。

### 2026-11-02 — B1 两段式检索完成（本沙箱，1 万行，同机，随机夹具向量）
- 做了：`Candidate` 去掉正文，三通道只取 `memory_id, version_id, score`；`MemoryRetriever` 融合分页后调用新增的 `CandidateProvider.contents()` 只读当前页正文（Postgres 与内存适配器都实现；按租户过滤，查不到的版本直接丢弃而不是返回空正文）；候选上限改成配置 `MEMORY_RETRIEVAL_CANDIDATE_LIMIT`，**默认仍是 1000，没有降到 200**：API 允许 offset 到 2900，降到 200 会让深分页变空，而我们没有开发集召回数据，PLAN 第 5 节也要求不盲降。
- 测量（`scripts/bench/retrieval_read_path.py`，同一脚本、同一数据、改前 `605a079` 对改后，各 3 次，每类 20 个查询，1 万行、平均正文 849 字节、pgvector 0.6.0、2 核同机；字节数是字符串长度估算，不是线上抓包）：
  - 候选阶段从数据库取回的正文量（中位）：词法窄 270,772 → 16,983 字节；词法宽 848,122 → 16,967；词法+结构化 1,119,850 → 16,981；向量+词法 1,119,921 → 17,036。降了约 16–66 倍。
  - 延迟 p50（中位，范围）：词法窄 679 ms（617–692）→ 673 ms（606–707）；词法宽 1862 ms（1788–1904）→ 1869 ms（1760–2006）；词法+结构化 656 → 630 ms；向量+词法 775 → 719 ms。**每类前后范围互相重叠，不能说延迟改善。**
- 为什么延迟没变：英文词法通道对每一行现算 `to_tsvector('english', content)`（没有对应索引），1 万行就要 0.6–1.9 s，这部分主导了总时间；客户端和数据库同机，省下的字节也没有网络传输开销可省。所以 B1 现在**只能**说"减少了数据库到应用的传输和反序列化量"，延迟收益要等 B2（建索引）之后才可能显现，真实跨机部署下传输量的影响本环境没测。
- 新增测试：单测 3 个（只取当前页正文、分页拼起来无重叠无遗漏且空页不触发第二阶段、正文读不到的命中被丢弃）；集成测试 3 个（`contents()` 取不到别的租户的版本、候选不带正文且页内容正确、候选上限对每通道生效）。
- 四道门（本沙箱 localpg）：482 passed（排除 `test_b0_harness`）；ruff（`src tests migrations`）通过；mypy strict 102 文件无错；foundation 8/8。`scripts/bench/pipeline_latency.py` 有一条 ruff `ASYNC220`（C1–C3 提交带来的，不在闸门范围，未处理）。
- 踩坑：基准一开始的"窄查询"带了词表里的常用词，几乎全表命中，分不出窄和宽，已改成只用标记词；alembic 日志写 stdout，基准要用 `--out` 取 JSON。
- 下一步：B2——给英文词法通道补 GIN 索引并对比 `EXPLAIN`；B2 的"改前"数据就是本次 `b1-after-10k-*.json`。

### 2026-11-02 — B2 完成：执行计划发现 GIN 索引在 RLS 下用不上，改为存储 tsvector 列（本沙箱，1 万行，同机）
- 发现（`explain_read_path.py` 抓取 provider 实际发出的 SQL 再 `EXPLAIN ANALYZE`）：英文词法通道是 Seq Scan，数据库侧窄查询 626 ms、宽查询 1778 ms，时间花在对每行现算 `to_tsvector('english', content)`。对照实验：同一条 SQL，超级用户（绕过 RLS）走 `Bitmap Index Scan` 仅 1.95 ms；应用角色（RLS 生效）永远是 Seq Scan，即使 `enable_seqscan=off` 也只把 `@@` 当 Filter。原因是 `ts_match_vq` 等 `@@` 实现不是 leakproof（`pg_proc.proleakproof=false`），PostgreSQL 不允许非 leakproof 条件推到 RLS 策略之下做索引条件。**推论：现有 `simple` 与中文 bigram 两个 GIN 索引，应用角色同样一直没用上**；我也验证过只加英文索引、或把配置名从绑定参数改成常量，计划都不变。
- 做了：迁移 `0010_stored_lexical_vectors` 加两个 `GENERATED ALWAYS ... STORED` 列 `lexical_en`、`lexical_zh`（版本行不可变，写入时算一次）；ORM 里设为 `deferred` 且该映射 `eager_defaults=False`（避免整实体读取和 INSERT 的 RETURNING 带上大向量）；词法通道直接读这两列。没有加 GIN 索引（应用角色用不上，只增加写入成本）。
- 测量（同一脚本、同一数据，改前 = `b1-after-10k-*`，改后 = `b2-after-10k-*`，各 3 次，1 万行、2 核同机、pgvector 0.6.0，p50 中位，范围互不重叠）：词法窄 673 → 10.8 ms；词法宽 1868 → 68.7 ms；词法+结构化 630 → 24.3 ms；向量+词法 719 → 95.5 ms（剩余主要是向量精确扫描，归 B3）。数据库侧 EXPLAIN：窄 626 → 13.1 ms，宽 1778 → 74.4 ms。`b2-explain-after-10k.json` 是在提交前的工作区上采集的（`dirty_tree: true`，基于 `73bd3e3`）。
- 局限（必须说清）：① 只测了 1 万行；10 万行的"改后"数据被中断，**没有数据，不得写成已测**。② 因为索引仍用不上，查询对单租户行数依然是线性的，只是每行便宜很多；10 万行以上要么再测，要么需要下面的安全决策。③ 代价：每个生成列约等于正文大小的额外存储；加列重写整张表并持有 ACCESS EXCLUSIVE 锁（1 万行约 6 秒）。
- 需要负责人决定：若要让词法检索随数据量次线性增长，只能让 GIN 被应用角色用上，选项（SECURITY DEFINER 且自行强制租户过滤的检索函数、把 `@@` 实现标 LEAKPROOF、独立无 RLS 的词法表）都会触及"RLS 是纵深防御"这条核心不变量，我没有擅自做。
- 验证：四道门（localpg）484 passed（排除 `test_b0_harness`，含升降级迁移测试）、ruff、mypy strict、foundation 8/8；新增 2 个集成测试（存储列与旧表达式逐值相等且整实体查询不含它们；中英文检索仍可用）。
- 下一步：B4 连接池快速失败；之后 B3。

### 2026-11-03 — 同步远端；B4 + D2 完成（新会话接手，沙箱 v230）
- 同步：`main` 无新提交（仍是 `53cba0f`）；远端 `optimize/stage3-6` 比本地多 3 个提交（C3 补测、B1、B2，由另一会话推送），已快进合并，未发生冲突。该沙箱自带 pgvector（`/usr/lib/postgresql/16/lib/vector.so`）。
- 做了：配置 `MEMORY_DB_POOL_SIZE`（默认 10）、`MEMORY_DB_MAX_OVERFLOW`（10）、`MEMORY_DB_POOL_TIMEOUT_SECONDS`（默认 2，原来是 SQLAlchemy 的 30 秒）、`MEMORY_DB_STATEMENT_TIMEOUT_MS`（默认 15000，0 = 不限）；`create_engine` 新增同名参数，**默认值等于旧行为，所以 worker 不变，只有 API 走新配置**；`api/infrastructure_errors.py` 按 SQLSTATE 分类，`SQLAlchemyError` 统一处理：连接池耗尽 → 503 `SERVICE_OVERLOADED`（`Retry-After: 1`）；磁盘满 / 资源上限（53100/53000/53200/53400）→ 503 `STORAGE_UNAVAILABLE`（30 秒）；语句超时 57014 → 504 `DATABASE_TIMEOUT`；连接类错误 → 503 `DATABASE_UNAVAILABLE`；其余数据库错误 → 500 `INTERNAL_ERROR`，不可重试。响应与指标里都不含异常文本。
- 验证：`test_pool_exhaustion.py`：连接池大小 1、占住唯一连接，请求在 0.3 秒池超时后 2 秒内返回 503，释放后恢复；错误体的 `request_id` 与响应头一致。语句超时配置在每个连接上生效（`SHOW statement_timeout`），并能真的取消 `pg_sleep`。四道门（localpg）496 passed（排除 `test_b0_harness`）、ruff、mypy strict、foundation 8/8。
- 局限：① 没有重做 B0 那种 1 QPS 的压测，所以**不能**说"1 QPS 不再超时"，只能说"池耗尽时现在 2 秒内明确失败而不是挂 30 秒"。1 QPS 大量超时的根因是 B1/B2（每次查询要扫全表并现算分词）加上池太小，B1/B2 已经把单次查询从 ~0.7–1.9 s 降到 ~10–70 ms（见上），这才是改善吞吐的主因，需要压测机验证。② D2 只验证了 SQLSTATE 映射，没有真的写满磁盘。③ 默认池 10+10 是我的取值，没有依据，需要在压测机上按数据库 `max_connections` 和实例数核定。
- 下一步：B3（HNSW 实验）→ C5 → D1 → E 系列。

### 2026-11-03 — 中途同步（未完成，供接手）
- B3：`scripts/bench/vector_index.py` 已能跑。已有数据 `measurements/b3-provider-sql-20k.json`（大租户 1.6 万行 + 8 个小租户各 500 行）：**provider 现在发出的 SQL，规划器从不使用 HNSW 索引**（即使建了索引、`ef_search` 取 40/200/1000），所以加索引对当前查询毫无作用。`measurements/b3-two-step-10k.json` 是改写成"先在 embeddings 上取最近邻再关联"的 SQL 形状后的第一轮数据（大租户 8000 行：精确扫描 p50 125 ms；HNSW ef=40/200/1000 为 11.5/17.8/36.2 ms，召回@20 为 0.54/0.80/0.97，返回候选数约 34/160/800），但**这个文件稍后会被带"无索引的改写形状"对照的新一轮覆盖**，不要据此下结论。
- C5：`EmbeddingWorker` 先查同租户同模型相同正文的已有向量，命中则复用（reason `EMBEDDING_REUSED`）；重建任务（payload `force`）永不复用；迁移 `0011_content_hash_index`。单测 `tests/unit/application/test_embedding_reuse.py` 与集成测试已写，**还没跑过**。
- D1：`SC4`（日志泄漏）在当前代码里读不出泄漏点（sqlalchemy 日志默认 WARN，字段白名单有效）；B0 的原始日志不在仓库，无法定位。计划写一个覆盖搜索查询、事件、worker 的端到端扫描测试作为守卫。

### 2026-11-03 — C5 验证完成、D1 守卫测试完成（新会话接手；沙箱 1 核 3 GB，apt 装 postgresql-16 + pgvector 0.6.0）
- 接手状态：分支 `optimize/stage3-6` 停在 WIP 提交 `852938e`（B3 实验、C5 代码，C5 测试未跑）。
- C5：`test_embedding_reuse.py` 与相关集成测试共 8 个，全部通过（此前从未运行过）。仍只有测试级证据，没有规模化的"调用次数前后"测量，不得写成已测量的节省比例。
- D1：新增 `tests/integration/test_query_text_not_logged.py`。用唯一标记串驱动 remember、events:batch、search、context、两种 422 校验失败、401 未认证，以及真实抽取 worker 一次；根 logger 开到 DEBUG（含 sqlalchemy/httpx 等第三方 logger）并收集全部 span，断言任何标记串都不在日志消息、格式化参数、异常文本、`agent_memory_fields` 或 span 里。**变异验证**：临时在搜索路由里加一行把 `body.query` 写进日志，测试立即失败，说明守卫非空转；改动已还原。结论只能是"当前代码下，这些路径没有泄漏"；B0 原始日志不在仓库，B0 报告的 117 次泄漏无法复现也无法定位，不得写成"已修复"。
- 四道门（localpg，排除 `test_b0_harness`）：C5 之后 502 passed、ruff 通过、mypy strict 103 文件无错、foundation 8/8；D1 测试加入后单独通过（1 passed），全量待下一次提交前重跑。
- 未完成：B3 结论仍未写（见上一条中途同步，实验数据文件会被覆盖，先重跑再下结论）；C4、D3、E1–E4、STORY.md 待做。
- 下一步：D3 → E2 → E1 → E4 → E3 → C4 → B3 收尾 → STORY.md。

### 2026-11-03 — D3 完成：已删除记忆的正文/向量物理清理命令（本沙箱 localpg）
- 现状：`POST /v1/deletion-requests` 只把记忆置为 `deleted` 并返回 `pending_physical_cleanup`，版本行里的正文、两个由正文生成的词法向量、嵌入向量都还在，也没有执行者（B0 的 LC7 就是这个）。
- 做了：`infrastructure/purge.py` 的 `purge_deleted_memories`，CLI `python -m agent_memory.workers.purge --tenant-id <uuid> --older-than-days N [--execute]`。**默认预演**；`--older-than-days` 必填、没有默认值；单租户、一次一个事务，幂等（重跑返回 0）。对已删除且早于保留期的记忆的每个版本：`content` 置空（生成列 `lexical_en/zh` 随之变空）、`structured_content` 置 `{}`、`reason` 置 NULL、`content_hash` 换成固定标记（同时是"已清理"标志，避免用哈希验证猜测）、删除 `memory_embeddings` 行、把未完成的 `embed_memory` 任务置为 `dead/MEMORY_PURGED`（防止 worker 用空文本重建向量）；每个记忆写一条 `memory.purge` 审计，不含正文。版本行、记忆行、ID、时间戳、状态保留（血缘和外键依赖它们）。输出只有计数。
- 验证（`test_purge_deleted.py`，1 passed）：清理前正文、词法向量、嵌入向量俱在；保留期未到时 `execute=True` 也不动；预演不改任何数据；执行后正文为空、词法向量为空、嵌入向量被删、任务置 dead；同租户的存活记忆和另一租户的已删除记忆原样不动；审计无正文；重跑为 0；清理后跑 embedding worker 不会把向量建回来、存活记忆照常建向量；清理后搜索词法零命中且不返回该记忆。四道门（localpg，排除 `test_b0_harness`）：504 passed、ruff、mypy strict 105 文件、foundation 8/8。
- **不在范围内，不得宣称已做**：① 源 `events` / `evidence` 里的原始文本（这是另一个保留期问题，需要负责人定策略）；② WAL、从库、备份，以及尚未 vacuum 的死元组（PostgreSQL 里 UPDATE 只是产生新行版本，旧版本在 vacuum 前仍在磁盘上，不是安全擦除）；③ 自动调度——现在只有手动命令；④ 没有 CLI 级别的端到端测试，测的是同一个函数；⑤ 没有大数据量下的耗时/锁测量。
- 需要负责人决定：保留期默认值（命令里故意不设）；是否把清理挂到定时任务；源事件正文的保留与清理策略。已同步 `README.md` 已知缺口表与 `AGENTS.md` 的相关口径。
- 下一步：E2（精确重复去重）→ E1 → E4 → E3 → C4 → B3 收尾 → STORY.md。

### 2026-11-03 — E2 完成：抽取候选的精确重复去重（本沙箱 localpg）
- 规则：同租户、同 `memory_type`、同作用域（kind/workspace/subject 全等），且已有记忆处于 `candidate` / `needs_review` / `active`，并且当前版本正文在 NFKC + casefold + 空白折叠后相等，则**不新建记忆**，只给已有的当前版本追加一条 `supports` 证据（该事件已经链接过该版本则不重复加）。`deleted` / `rejected` / `invalidated` / `superseded` / `archived` 的记忆不吸收新证据：删除后再次抽取到同一句话会得到新的候选。
- 实现：版本表新增 `dedup_hash`（规范化正文的 SHA-256，写入版本行时由应用算；迁移 `0012_dedup_hash` 加列、加 `(tenant_id, dedup_hash)` 索引，并在迁移里按批回填，回填用的规范化函数在迁移里冻结了一份）。哈希只用来缩小范围，命中后还会比较规范化正文，所以哈希碰撞不会合并不同的记忆。`commit_candidates` 里先查重。清理命令（D3）同时把 `dedup_hash` 置 NULL，因为哈希能被拿来验证猜测。
- 验证：单测 3 个（规范化与不等价的例子，含中文）；集成测试 3 个：大小写/空白不同的重复只追加证据；换工作区算新记忆；末尾多一个句号**不**算重复（已知边界）；删除后的记忆不吸收证据；manual 模式下候选也去重；同一事件里重复的两个候选不产生第二条证据。**变异验证**：把查重改成永远返回"没有重复"，两个集成测试都失败，已还原。迁移测试：在 0011 上插入存活与已清理两种版本，升到 head 后存活版本的哈希正确、已清理的保持 NULL，并验证降级再升级可走通。四道门（localpg，排除 `test_b0_harness`）：510 passed、ruff、mypy strict 106 文件、foundation 8/8。
- 改了一个旧测试的输入：`test_llm_pipeline` 里 mock 模型对两个不同事件返回完全相同的文本，原来落成两条候选，现在按 E2 会合并成一条。我让 mock 对不同事件返回不同文本，保留"两个事件各产出候选"的原意，断言本身没有放松；重复合并的行为由 `test_candidate_dedup.py` 单独覆盖。
- **局限，不得夸大**：① 只覆盖**抽取路径**；显式写入（`POST /v1/memories`）和纠正版本不去重，因为那是调用方明确的意图。② 只做精确匹配（NFKC、大小写、空白）；标点不同、同义改写都不算重复，语义去重没做。③ 迁移前就已存在的重复不会被合并，只是以后的候选会和它们去重（回填会给它们补哈希）。④ **没有数据库唯一约束**，也没有对"两个并发 worker 同时抽取到同一句话"加锁：C3 的 `--concurrency` 下两个循环可能同时查不到、各建一条，造成漏去重。这个竞态没有测试，也没有测量。⑤ 回填在迁移里同步执行，大表要放进维护窗口。⑥ 没有测去重对检索质量或候选数量的真实影响（没有真实抽取数据）。
- 下一步：E1（证据引用）→ E4 → E3 → C4 → B3 收尾 → STORY.md。

### 2026-11-03 — E1 证据引用完成（本沙箱 localpg）
- 现状：`evidence` 表（版本→事件，角色 `triggered_by/supports/contradicts/verified_by`）早就有，但检索结果和 context 里 `evidence_refs` 恒为空占位。
- 做了：`/v1/memories/search` 每条命中新增 `evidence`（至多 5 条）与 `evidence_total`；`/v1/memories/context` 把 `evidence_refs` 填成至多 3 条 `{event_id, role}`，多于 3 条时才附 `evidence_total`（没有证据的条目渲染结果与改前逐字节相同，所以旧预算测试没动）。引用字段：`event_id`、`role`、`event_type`、`occurred_at`、`session_id`、`sequence_number`——**没有事件正文**。带 session/sequence 是因为事件接口只有写入、没有按 ID 读取，只给 `event_id` 调用方无处可查；它们是调用方自己写入的坐标。
- 设计：沿用 B1 的两阶段，证据只对当前页（≤100）用**一条**窗口函数查询取回（`CandidateProvider.evidence()`，Postgres 与内存适配器都实现）。封顶时排序为 origin（`triggered_by`）→ `contradicts` → `verified_by` → `supports`，同角色内新的在前，所以 E2 追加再多的 `supports` 也挤不掉起源和反驳。预算紧到连"空内容条目"都放不下时，context 先丢引用（`evidence_total` 保留）而不是丢记忆。有证据**不**改变 `trust` 标签（仍是 `unverified_historical_reference`）。
- 验证：单测 5 个（只为当前页取证据、空页不取、封顶且保留总数、context 紧凑/封顶/无证据逐字节不变/紧预算先丢引用）；集成测试 3 个（真实事件→抽取→E2 追加后：封顶 5 条与总数 7、起源在首位且坐标正确、context 引用与 `event_id` 对得上、别的租户读不到；追加 `contradicts`/`verified_by` 后封顶仍保留它们；HTTP 与 SDK 响应键集合恰为 6 个字段、不含事件内容、显式写入的记忆证据为空、跨租户无结果）。**变异验证**：分别去掉角色排序、让 `evidence()` 返回空、让 context 路由不透传证据、取消封顶，对应测试各自失败（4/4）。四道门（localpg，排除 `test_b0_harness`）：539 passed、1 skipped（B3 需要 pgvector 0.8 的测试）、ruff、mypy strict 106 文件、foundation 8/8，含"SDK 覆盖全部路由"测试。
- 代价（`scripts/bench/retrieval_read_path.py --with-evidence`，每条记忆 1 个事件和 1 条证据，同一脚本同一数据，改前 `1bd6cbf` 对改后，各 3 次，1 万行，2 核同机，无向量，p50 中位）：词法窄 10.5 → 13.5 ms；词法宽 65.9 → 67.6 ms；词法+结构化 25.4 → 27.0 ms。前后范围互不重叠，即每次搜索多约 1.6–3 ms，是多出来的那条查询，对最快的查询相对比例不小。"改后"是在 `1bd6cbf` 之上、提交前的工作区采集的。没有测过证据很多的记忆或更大规模。
- 局限（不得夸大）：① 只有抽取路径产生证据；显式写入和纠正版本没有来源事件，列表为空。② 证据按**版本**挂，纠正产生的新版本不继承旧版本的证据。③ 引用只是指针，**不**等于"已验证"，也没有做证据质量评估。④ 没有按 ID 读取事件的接口，我没有新增（超出 E1 范围），消费者靠 session/sequence 对回自己的记录。
- 下一步：E4（冲突标注）→ E3（上下文打分）→ C4/B3 的 PLAN 收尾 → STORY.md。

### 2026-11-03 — B3 与 C4 完成（tx 服务器，Docker PG16）

- B3 做法见 5 · B3。代码：`PostgresCandidateProvider(vector_search="nearest_first" | "exact")`，默认 `nearest_first`，只在 pgvector ≥ 0.8 时走新形状，否则退回精确扫描（0.8 以下会被过滤截断）。配置项 `MEMORY_VECTOR_SEARCH`、`MEMORY_VECTOR_EF_SEARCH`。
- B3 证据：`measurements/b3-nearest-first-{8000,20000}-{1000,100}.json`，4 组、每组 30 条查询，含 p50/p95、召回@20、EXPLAIN 计划节点。**四组里 `provider_nearest_first_*` 与 `provider_exact_*` 的 `uses_hnsw_index` 全是 false**，这是"不上索引迁移"的直接依据。
- B3 测试：`tests/integration/test_vector_search.py` 4 个（最近邻与精确扫描头部一致；跨租户与归档不泄漏；缺迭代扫描时退回精确形状且不发 `hnsw.ef_search`；新形状确实把物化 CTE 与 `ef_search` 探测发到库里）。**删掉了原来的"规划器必须选索引"测试**——它靠夹具行数凑规划器，40 / 3000 / 8000 行都失败过，钉住的是行数不是行为。
- C4 做法见 5 · C4。代码：迁移 `0013_job_priority`、`JobPriority`、`ingest_batch(priority=)`、`commit_candidates` 里设 GUC。
- C4 证据：`measurements/c4-priority-{off,on}-{1,2,3}.json`，1500 条 bulk 积压 + 5 条交互事件，每个配置 3 次。交互事件 ingest → active 的 p50 依次为 40.952 / 24.018 / 29.748 s（中位 29.7 s）与 0.445 / 0.076 / 0.223 s（中位 0.22 s），**两组范围互不重叠**。bulk 的 p50 中位 21.9 → 25.3 s，是 5 条交互任务插队应付的代价；只有 1 个 worker、1 个客户端，不要当吞吐结论。
- 测量口径：B3 与 C4 的 JSON 都是 `dirty_tree: true`，因为工作区比当时 HEAD 多出的是本轮提交里的文档与 `scripts/bench/*.py --reset` 的 schema ACL 修补（重建 public 后不加 `GRANT USAGE`，应用角色连表名都解析不了）；被测的 `src/` 与 `975eee4` 一致。
- 四道门（tx，pgvector 0.8.6，Docker）：541 passed、ruff、mypy strict 106 文件、foundation 8/8。本沙箱 localpg 是 pgvector 0.6.0，B3 有一个测试在那边 skip，属版本差异不是缺陷。
- 局限（不得夸大）：① 没有语义向量，召回数字不代表检索质量。② 规模到 2 万，没到 10 万。③ C4 只验证了"积压时交互任务不再排队"，没有测多 worker 抢同一租户，也没有测优先级造成的饥饿。④ 优先级只有两档，且 outbox → job 这一跳不分级。
- 下一步：E4（冲突标注）→ E3（上下文打分）→ STORY.md。

### 2026-11-03 — E3 与 E4 完成（tx 服务器）

- E3 做法见 5 · E3。代码：`application/context_scoring.py`、`context_builder` 改为按 `分数 ÷ 占用` 贪心、`CandidateProvider.facts()`（Postgres 与内存两个实现）、`RetrievalHit` 带类型 / 创建时间 / 权威级别 / 主体、配置项 `MEMORY_CONTEXT_*`。context 路由不再从响应模型重建 hit（否则正好丢掉这些元数据）。
- E3 测试：单测 16 个（三因子各自能改变顺序、半衰期按类型、权重归零被拒、缺时间戳按中性 0.5、确定性、短条目赢过长条目）；集成 3 个（真库读出类型与 30 天前的年龄、跨租户拿不到别人的 facts、同分时权威高的排第一）。**没有**质量指标——本环境没有真实向量。
- E4 做法见 5 · E4。代码：`application/conflicts.py`，只做"同主体 + 同类型 + 词面重叠但正文不同"的规则，标签是 `similar_text`。渲染时剪掉未装进预算的引用。
- E4 测试：单测 9 个（互标、跨主体不标、跨类型不标、完全相同交给 E2、不相关不标、短句失效的已知盲点、阈值可移动分界线、封顶取最相似的、空包不花钱）；集成 1 个（真库两条改口式记忆在 context 里互相指向）。
- **诚实边界**：`conflicts` 字段从字符串 `"not_assessed"` 改为列表，这是 context 渲染格式的变化；空列表表示"查过没有"，不再表示"没查"。E4 不判断语义，短句标不出来。
- 四道门（tx）：571 passed、ruff、mypy strict 108 文件、foundation 8/8。
- STORY.md 已写（第 10 节的交付约定）：现象、原因、做法、改前改后数字、"还不能说的话"、十个追问、诚实边界。所有数字可追到 measurements/ 或提交号。
- 到此 A1、B1–B4、C1–C5、D1–D3、E1–E4 全部完成；剩下的只有第 9 节需要负责人配合的四件事。

## 9. 需要负责人决定或配合的事项

1. A1 激活策略默认值（见 5 · A1）。
2. 把 Agent 重做的 B0 报告与数据推送到仓库（目前仓库里没有，优化文档引用的 B0 数字都只能标"汇报"）。
3. 优化完成后，用真实 B0 配置在本分支上重跑开发集，才能写"质量指标提升了多少"。
4. 是否合并 `optimize/stage3-6` 到 `main`（我不会自行合并或推送 `main`）。

## 10. 给负责人的面试文档

优化做完后写 `docs/optimization/STORY.md`，约定：
- 读者是负责人本人，用于面试讲述；不是 agent 交接文档。
- 结构：这个项目是什么 → 我先量了什么、发现了什么 → 每个优化：问题、原因、做法、改前改后数字、**还不能说的话** → 可能被追问的 10 个问题与答法 → 诚实边界（哪些数字是本地微基准、哪些没测）。
- 所有数字必须能追溯到 `measurements/` 下的文件或提交号。
