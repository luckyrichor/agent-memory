# 企业级 Agent 记忆系统架构设计

- 日期：2026-08-30
- 状态：设计基线
- 目标产品：面向 Coding Agent 与其他企业 Agent 的通用记忆平台
- 基准交付形态：多租户 SaaS，同时支持单租户私有化和本地嵌入运行

## 1. 摘要

本系统提供一个可治理、可验证、可扩展的长期记忆层。Agent 通过薄 SDK 接入；企业部署使用独立 Memory Service；本地开发和离线场景可切换到嵌入式适配器。系统第一版支持情景记忆、语义记忆和程序性记忆，不替代 Agent Runtime 的工作记忆、状态机或企业知识库。

核心架构决策如下：

1. 采用“薄 SDK + 独立 Memory Service + 可替换嵌入式适配器”。
2. 显式记忆命令同步处理，自动经验沉淀通过事件日志异步提炼。
3. Event 是不可随意改写的证据；Memory 有稳定身份；内容变化通过不可变 MemoryVersion 表达。
4. PostgreSQL 是系统事实来源，pgvector 是可重建语义索引，大对象通过 ObjectStore 抽象保存。
5. `tenant` 是强隔离边界；`workspace`、`user` 和 `agent` 是可组合适用维度，不构成单一层级。
6. 检索采用“权限硬过滤、混合召回、可解释重排、冲突处理、Token 预算组装”。
7. Agent 和 LLM 均不属于可信边界。它们只能生成候选，正式激活、Scope、权限和高风险策略由确定性代码控制。
8. 可靠性采用至少一次投递、端到端幂等、事务 Outbox、可恢复 Worker 和乐观并发控制。
9. 记忆质量必须通过写入、检索、上下文和端到端任务四层评测证明。

## 2. 目标与非目标

### 2.1 目标

- 支持多租户、多用户、多 Workspace 和多类 Agent。
- 从 Agent 事件中提取具有未来价值的候选记忆。
- 支持用户或受信任系统显式创建、纠正、确认和遗忘记忆。
- 保存来源、证据、版本、可信度、适用范围和生命周期状态。
- 支持关键词、结构化和向量混合检索。
- 在固定 Token 预算内生成可追踪的 Memory Context Packet。
- 支持跨会话复用，同时避免跨租户、跨 Workspace 和跨权限泄露。
- 支持本地嵌入、企业私有化和多租户 SaaS 三种部署形态。
- 具备审计、回放、删除传播、线上观测和离线评测能力。

### 2.2 第一版非目标

- 不实现 Agent 工作流状态机和精确任务检查点。
- 不管理完整聊天历史，也不将聊天历史等同于长期记忆。
- 不替代代码仓库、文档系统、工单系统等事实来源。
- 不构建通用企业知识图谱。
- 不在第一版引入 Kafka、Elasticsearch 或独立图数据库。
- 不支持任意动态 Scope DSL、复杂组织部门继承和跨租户共享。
- 不声称一次 Agent 推测可以自动升级为企业政策。

## 3. 首个端到端用例

首个用例是 Coding Agent 复用故障解决经验：

1. Agent 执行构建并失败。
2. Agent 检查环境，发现本机为 arm64。
3. Agent 发现安装了 x86_64 依赖。
4. Agent 替换依赖后重新构建，测试通过。
5. 系统从事件窗口提取 Workspace 级情景记忆。
6. 后续相似故障触发混合检索。
7. Agent 将记忆作为排查线索，并验证当前环境后再行动。
8. 新任务结果通过 Feedback 回流，增强、修正或否定旧记忆。

该用例覆盖事件摄取、异步提炼、Evidence、版本、Scope、混合检索、上下文组装、反馈和生命周期闭环。

## 4. 概念边界

### 4.1 Context

Context 是本次模型推理实际获得的系统指令、对话、代码片段、工具结果和检索记忆，具有临时性并受 Token 上限约束。

### 4.2 State

State 是任务执行的精确状态，例如步骤、分支、工具调用结果和审批状态。State 由 Agent Runtime、数据库和状态机维护，不依赖自然语言记忆恢复。

### 4.3 Knowledge

Knowledge 是代码、文档、Schema、工单和技术规范等外部事实来源。Memory 可以引用和索引 Knowledge，但不能复制后冒充当前事实；需要保留文件、版本、提交或资源标识以便验证。

### 4.4 Memory

Memory 是从历史交互和执行经验中沉淀的、未来可能有帮助的信息。它可能不完整、过期或冲突，因此必须带有来源、时间、Scope、版本、权威等级和验证状态。

### 4.5 记忆类型

- Episodic：一次任务、故障、决策和结果。
- Semantic：经过证据支持的稳定事实、约束或归纳结论。
- Procedural：Agent 未来应如何工作，包括操作规则和检查策略。

三类记忆可以转化：一次故障先形成 Episodic，多次验证后形成 Semantic，再提炼为 Procedural。跨类型或跨 Scope 升级必须由策略控制。

## 5. 总体架构

```text
Agent Runtime / Agent Framework
        │
        ▼
Thin Memory SDK
├── Runtime Context Adapter
├── Event Buffer
├── Retry / Trace / Serialization
└── Remote or Embedded Transport
        │
        ▼
Memory API Gateway
├── Authentication
├── Tenant Binding
├── Rate Limit
└── Request Validation
        │
        ▼
Memory Application Layer
├── Event Ingestion
├── Explicit Memory Commands
├── Extraction and Consolidation
├── Policy and Authorization
├── Retrieval and Ranking
├── Context Builder
├── Feedback
└── Deletion Orchestration
        │
        ▼
Memory Domain and Persistence
├── PostgreSQL
├── pgvector
├── ObjectStore
└── Cache Adapter
        │
        ▼
Workers
├── Extraction
├── Embedding
├── Consolidation
├── Deletion
└── Evaluation / Maintenance
```

系统首先实现为模块化单体：API 与 Worker 可以是同一代码库和同一发布单元，但通过清晰接口隔离。只有出现可测量的吞吐、隔离或发布需求后，才拆成独立微服务。

## 6. 部署形态

### 6.1 本地嵌入模式

```text
Agent → SDK → Embedded Adapter → SQLite/PostgreSQL → In-process Worker
```

用于教学、离线工具和单机 Agent。保持与远程模式相同的领域对象、幂等规则和策略接口。SQLite 是便利适配器，不是企业基准数据库。

### 6.2 单租户私有部署

```text
Enterprise Agents → Memory API → PostgreSQL/pgvector → Worker → Object Storage
```

每家公司拥有独立部署与数据面。认证可接入企业 IdP，数据库和对象存储由企业托管。

### 6.3 多租户 SaaS

```text
Tenant Agents → Shared API Tier → Shared/Sharded Data Tier → Worker Pools
```

所有逻辑表带 `tenant_id`；应用层显式过滤与 PostgreSQL RLS 双重保护。初期共享数据库，规模和隔离需求出现后按 Tenant 分片或为高要求租户提供独立数据面。

## 7. Scope 与权限模型

`tenant` 是绝对隔离边界。`workspace`、`user`、`agent` 是正交适用维度。

第一版 Scope：

- `tenant`：租户内共享，只有高权限主体可创建。
- `workspace`：对 Workspace 中被授权成员生效。
- `user_global`：对一个用户的所有允许 Workspace 生效。
- `user_workspace`：只对某用户在某 Workspace 生效。

Agent 适用性通过独立约束表达，例如只允许 `coding_agent` 或 `code_review_agent` 使用。

Scope 表示内容在哪里有意义；Permission 表示调用者是否能读写。检索顺序固定为：认证、服务端绑定 Tenant、授权过滤、Scope 匹配、候选召回。禁止先全库向量检索后再过滤。

冲突优先级不按范围大小机械决定。企业强制政策、项目确认规范、用户偏好和 Agent 推测按照内容类型、来源权威和证据处理。

## 8. 核心领域模型

### 8.1 Event

不可随意改写的历史证据，记录允许持久化的用户输入、工具调用、测试结果、任务结果和确认动作。Event 不保存模型隐藏推理。

### 8.2 Memory

记忆的稳定身份，保存类型、状态、Scope、当前版本和乐观并发 revision。

### 8.3 MemoryVersion

记忆某一时刻的不可变内容，保存自然语言、结构化内容、Confidence、Utility、Authority、验证状态和有效时间。

### 8.4 Evidence

连接 MemoryVersion 与 Event，角色包括 `supports`、`contradicts`、`triggered_by` 和 `verified_by`。

### 8.5 MemoryRelation

表示 `derived_from`、`supports`、`contradicts`、`supersedes` 和 `duplicates`。

### 8.6 Embedding

绑定到具体 MemoryVersion 和 Embedding 模型，是可重新生成的检索索引，不是事实来源。

### 8.7 AuditLog

记录谁在何时读取、创建、修改、确认、拒绝或删除了哪条记忆。AuditLog 与 Agent 工作 Event 分离。

```text
Event ──Evidence──► MemoryVersion ──► Embedding
                         │
                         ▼
                       Memory ──Relation──► Memory
```

## 9. 写入与提炼

### 9.1 双路径写入

```text
用户明确记忆命令 → 同步 Memory Command → Active / Needs Review
Agent 自动学习     → Event Log → Outbox → Async Worker → Candidate
```

用户显式命令需要立即返回已生效、待审核或明确失败；自动学习不能阻塞 Agent 主任务。

### 9.2 自动提炼管线

1. 选择完整 Event Window。
2. 确定性预筛选心跳、重复输出和无状态变化事件。
3. 敏感信息检测、内容清理和模型数据出境策略检查。
4. LLM 生成结构化候选，不直接写正式记忆。
5. Schema、Tenant、Evidence 和 Scope 校验。
6. 精确、关键词和语义去重。
7. 冲突检测和关系建立。
8. Policy Engine 决定拒绝、待审核或激活。
9. 为激活版本生成全文和向量索引。

### 9.3 信任维度

- Confidence：结论正确的可能性。
- Utility：未来复用价值。
- Authority：来源在当前内容类型上的权威等级。

不得将三者合并成一个不可解释的质量分。

参考信任级别：Agent 推测、单事件支持、多事件支持、工具或测试验证、用户明确确认、企业权威政策。不同记忆类型使用不同权威规则。

### 9.4 自动激活策略

可自动激活：用户明确保存的非敏感个人偏好，以及具有明确工具验证的低风险 Workspace 经验。

进入审核：跨 Workspace 推广、与已确认记忆冲突、高风险程序性规则、证据不足但影响大的内容。

## 10. 检索与上下文组装

### 10.1 检索漏斗

```text
Request Principal and Scope
        ↓
Authorization Hard Filter
        ↓
Query Planner
        ↓
Structured + Lexical + Vector + Recency + Relation Candidates
        ↓
Fusion and Deduplication
        ↓
Explainable Reranking
        ↓
Conflict and Staleness Handling
        ↓
Token Budget and Diversity
        ↓
Memory Context Packet
```

### 10.2 Query Planner

输入包括查询文本、任务 Intent、实体、错误码、文件、平台、时间约束、偏好记忆类型和 Token 预算。Agent Runtime 可提供结构化信息，Service 只补充而不信任未经验证的 Scope。

### 10.3 候选生成

- 结构化过滤：类型、状态、时间、Workspace 和验证状态。
- 关键词/BM25：错误码、文件名、类名、版本和命令。
- 向量：语义改写和概念相似。
- Recency：近期仍有效的内容。
- Relation：从情景经验扩展到派生程序规则。

### 10.4 重排

可解释特征包括语义相关性、关键词分、Scope 匹配、Confidence、Authority、验证状态、有效时间、历史效果、冲突风险、过期风险和冗余。第一版使用可配置加权与明确规则，后续通过 Golden Dataset 调整。

### 10.5 Memory Context Packet

返回 MemoryVersion、类型、内容、可信状态、证据引用、适用说明、冲突信息和 Token 统计。检索结果是历史参考，不能覆盖系统指令、工具权限和人工审批要求。

`MemoryRetriever` 与 `MemoryContextBuilder` 分离：前者找候选，后者决定哪些内容和怎样的表达进入模型上下文。

## 11. 生命周期、冲突和删除

状态：

```text
candidate → rejected | needs_review | active
active → superseded | invalidated | archived | deleted
```

- Superseded：旧内容曾正确，但被新结论取代。
- Invalidated：证据表明原结论错误。
- Archived：退出实时检索但保留历史用途。
- Deleted：立即退出检索，并异步清理派生数据。

删除流程：鉴权、创建 DeletionRequest、事务内禁用检索、Outbox、清理 Embedding/缓存/ObjectStore、根据 Evidence 重新评估派生记忆、验证目标、完成操作。

删除聊天、删除记忆和删除账户是不同命令。删除原始事件后，派生记忆根据剩余证据和内容敏感性选择降级、重写或删除。最小审计记录不得保留被要求删除的正文。

## 12. 逻辑模块划分

### 12.1 SDK

- `RuntimeContextProvider`：获取 Workspace、Session、Agent 和任务上下文。
- `EventBuffer`：有界本地缓冲、批量发送和退出刷新。
- `MemoryClient`：`record_event`、`remember`、`search`、`build_context`、`feedback`、`forget`。
- `RemoteTransport`：HTTP/gRPC 调用、超时和重试。
- `EmbeddedTransport`：进程内调用相同应用接口。
- Framework Adapters：面向不同 Agent 框架的 Hook，不包含企业策略。

### 12.2 API Gateway

负责认证、Tenant 绑定、请求大小限制、速率限制、Schema 校验、Trace 建立和协议错误映射。它不实现记忆提炼与排序。

### 12.3 Event Ingestion

负责事件合法性、幂等、Session 顺序、对象存储卸载和 Outbox 写入。它不决定事件是否应形成长期记忆。

### 12.4 Explicit Memory Command

处理用户明确创建、纠正、确认和遗忘。负责同步返回明确状态，但仍调用 Policy Engine。

### 12.5 Extraction Orchestrator

构建 Event Window、执行预筛选、调用 Extractor、校验输出并提交候选。Extractor 是可替换接口，模型 Prompt 和版本必须可追踪。

### 12.6 Policy Engine

执行 Scope、Authority、敏感性、激活、跨 Scope 升级和高风险程序规则策略。Policy 输入输出结构化、可测试、可解释；LLM 不做最终授权决策。

### 12.7 Consolidation Engine

负责去重、合并证据、创建新版本、冲突、取代和派生关系。通过 Memory revision 实现乐观并发。

### 12.8 Retrieval Orchestrator

组织授权过滤、Query Plan、候选生成、融合和重排。Candidate Provider 通过接口扩展，第一版实现 Structured、Lexical 和 Vector。

### 12.9 Context Builder

执行可信状态标注、冲突说明、多样性、Token 预算和安全包装，产生可审计 Context Packet。

### 12.10 Feedback Service

记录记忆是否有帮助、错误、过时、不安全或被忽略。Feedback 不直接修改 Confidence，由聚合策略和验证事件触发版本更新。

### 12.11 Deletion Orchestrator

创建删除计划、立即禁用读取、遍历血缘、调度清理、验证结果和保留最小审计证明。

### 12.12 Observability and Evaluation

统一 Trace、Metrics、Audit、决策解释、离线回放和 Golden Dataset 执行。

## 13. API 与 SDK 契约

SDK 核心接口：

```text
record_event
remember
search
build_context
feedback
forget
flush
```

HTTP API：

```text
POST /v1/events:batchIngest
POST /v1/memories
GET  /v1/memories/{memory_id}
GET  /v1/memories/{memory_id}/versions
POST /v1/memories/{memory_id}/versions
POST /v1/memory-search
POST /v1/context-packets
POST /v1/memory-feedback
POST /v1/deletion-requests
GET  /v1/operations/{operation_id}
GET  /v1/capabilities
```

服务端根据凭证建立 `RequestPrincipal`，客户端不能自行决定 Tenant、真实用户身份、管理员权限和允许访问的 Workspace。

写入使用 Idempotency-Key；版本更新携带 `expected_revision`。错误返回稳定业务码、`retryable` 和 `request_id`。SDK 只自动重试有幂等保证且服务端明确可重试的临时错误。

## 14. PostgreSQL 逻辑 Schema

核心表：

```text
events
memories
memory_agent_constraints
memory_versions
memory_evidence
memory_relations
memory_embeddings
memory_feedback
outbox_messages
jobs
deletion_requests
deletion_targets
audit_logs
```

所有核心主键和外键包含 `tenant_id`。关键唯一约束：

- `events(tenant_id, idempotency_key)`。
- `events(tenant_id, session_id, sequence_number)`。
- `memory_versions(tenant_id, memory_id, version_number)`。
- `memory_embeddings(tenant_id, memory_version_id, embedding_model)`。
- `jobs(tenant_id, job_type, idempotency_key)`。

`memories.current_version_id` 与 `revision` 在同一事务中更新；版本、Evidence 和 Outbox 同步提交。应用显式 Tenant 条件与 PostgreSQL RLS 双重隔离；普通应用角色不得绕过 RLS。

## 15. 可靠性与一致性

### 15.1 语义

- 至少一次投递，端到端幂等。
- Session 内 sequence，跨 Session 不假设全局顺序。
- Event 发生时间和接收时间分开。
- 业务写入与 Outbox 在同一事务。
- Worker 使用租约和 `FOR UPDATE SKIP LOCKED`。
- 记忆更新使用 revision 乐观并发。

### 15.2 自然幂等键

- 提取：Event Window Hash + Extractor Version。
- Embedding：MemoryVersion + Model + Content Hash。
- 合并：Source Memory Set + Policy Version。
- 删除：Deletion Request + Target Type + Target ID。

### 15.3 降级

- 检索故障与“没有记忆”必须区分；Agent 可无记忆继续低风险任务。
- 自动事件写入失败进入有界本地缓冲并可观察，不能无限占用磁盘。
- 用户显式 remember 不得静默失败，返回 Active、Pending 或明确错误。
- 删除请求接受后立即禁止检索；物理清理失败持续重试并告警。

## 16. 安全与威胁模型

### 16.1 信任边界

用户输入、Agent、仓库、网页、工具输出、MCP、旧记忆和 LLM 输出均视为不可信。API Gateway、Policy Engine、Authorization 和数据库约束构成确定性控制面。

### 16.2 主要威胁与控制

| 威胁 | 主要控制 |
|---|---|
| 跨租户泄露 | 服务端 Tenant 绑定、显式过滤、复合外键、RLS、攻击测试 |
| Memory Poisoning | 候选状态、来源等级、Evidence 校验、高风险规则审核 |
| Prompt Injection 持久化 | 指令与事实分离、外部内容低权威、Context 安全包装 |
| 敏感信息持久化 | 写入前检测、租户策略、拒绝或脱敏、Embedding 前复检 |
| 越权提升 Scope | Policy Engine 限制，项目事件不能自动生成 Tenant 规则 |
| 重放和重复写入 | Idempotency-Key、内容哈希、唯一约束 |
| 旧记忆误导 | 有效时间、版本、冲突关系、当前来源复核提示 |
| 删除不完整 | 血缘、Deletion Targets、立即禁用、异步验证 |
| 模型供应商暴露 | 数据最小化、模型路由策略、脱敏、私有部署适配 |
| 成本或资源耗尽 | 配额、速率限制、Event Window、批处理、Token 预算 |

程序性记忆不能覆盖系统指令、权限、人工审批和工具安全策略。Embedding 同样视为敏感派生数据。

## 17. 可观测性与评测

### 17.1 Trace

一次请求记录认证、Scope、查询计划、各召回器候选 ID、分数构成、过滤原因、注入版本、Token、延迟和后续 Feedback。普通日志优先记录 ID、哈希、分类和决策原因，正文只允许受控脱敏采样。

### 17.2 四层评测

1. 写入：Extraction Precision/Recall、Grounding、重复、冲突、敏感信息和 Scope 准确率。
2. 检索：Recall@K、Precision@K、MRR、NDCG、旧记忆误召回和冲突抑制。
3. 上下文：Token、去重、可信状态表达、实际采用和安全包装。
4. 端到端：任务成功率、工具调用、耗时、Token、成本和错误操作。

安全硬门槛：跨租户泄露、已删除记忆正常命中、未授权程序规则激活和秘密信息写入均为零容忍测试项。

测试集：Golden Extraction Dataset、Golden Retrieval Dataset 和 End-to-End Agent Scenarios。基线为 No Memory 与纯向量 Top-K；复杂系统必须证明优于基线。

## 18. 扩展路线

### 18.1 初期

- 单个模块化 API 服务。
- PostgreSQL + pgvector。
- PostgreSQL Outbox 和 Job Queue。
- 一个或少量 Worker 进程。
- 本地或 S3 兼容 ObjectStore。

### 18.2 出现证据后的扩展

- API 无状态横向扩展。
- Extraction、Embedding、Deletion Worker 按负载独立扩展。
- PostgreSQL 读副本承担允许弱一致的管理查询。
- 大 Tenant 分区、分片或独立数据面。
- 关键词检索达到已验证瓶颈后引入专用搜索引擎。
- Outbox 发布和吞吐达到瓶颈后引入消息平台。
- 只有图遍历成为核心且关系表无法满足时引入图数据库。

拆分依据是测量结果、故障隔离和团队所有权，而不是组件数量。

## 19. MVP 开发路线

### Phase 0：评测骨架

- 定义首个故障用例及变体。
- 建立 Golden Extraction 和 Retrieval 样本格式。
- 建立 No Memory 与 Naive Vector 基线接口。

### Phase 1：领域与显式记忆

- Memory、MemoryVersion、Scope 和 Evidence 领域对象。
- PostgreSQL Schema、迁移和 Repository。
- RequestPrincipal、Tenant 隔离与 RLS 测试。
- `remember`、查询详情、版本更新和基本删除禁用。
- 暂不调用 LLM。

### Phase 2：事件与异步提炼

- Event 批量摄取和幂等。
- Transactional Outbox、Job、Worker 租约和重试。
- 规则预筛选和可替换 Extractor。
- 使用可控假 Extractor 完成测试，再接入真实模型。
- Candidate、Policy 和 Evidence 校验。

### Phase 3：混合检索与 Context

- PostgreSQL 全文检索。
- pgvector 索引和 Embedding Worker。
- Structured/Lexical/Vector Candidate Providers。
- 可解释融合、重排、冲突和去重。
- Memory Context Packet 与 Token 预算。

### Phase 4：生命周期与反馈

- Supersede、Invalidate、Archive。
- Feedback 聚合。
- DeletionRequest、派生目标清理和状态查询。
- Evidence 重新评估。

### Phase 5：企业化加固

- 敏感信息策略。
- 高风险程序性记忆审核。
- Audit、Trace、Metrics 和管理查询。
- 跨租户、污染、重放、删除和降级测试。
- SaaS 与私有化部署配置。

## 20. 第一版验收标准

1. 故障事件重复发送不会产生重复 Event 或 Memory。
2. 提取记忆能引用真实 Event，并且不能扩大到未授权 Scope。
3. 同一故障的精确错误码和语义改写查询都能召回正确记忆。
4. 已验证记忆能够优先于高相似度的未验证猜测。
5. 被 Supersede、Invalidated 或 Deleted 的版本不会进入正常 Context。
6. Tenant A 无法通过任何查询读取、关联或推断 Tenant B 的记忆。
7. 恶意仓库指令不能自动激活高风险程序性记忆。
8. 显式删除接受后立即停止检索，所有派生目标可查询并最终清理。
9. 每个注入模型的 MemoryVersion 都能通过 Trace 回溯到检索决策和 Evidence。
10. 端到端故障场景相对 No Memory 和 Naive Vector 基线有可测量改善，且不跳过当前环境验证。

## 21. 已确定假设与风险

### 假设

- 首个实现以 Coding Agent 故障经验为核心负载。
- 企业基准数据库为 PostgreSQL，开发可使用 Embedded Adapter。
- 初期吞吐无需独立消息平台和搜索引擎。
- Agent Runtime 能提供 Workspace、Session、Agent Type 和任务事件。
- 外部身份系统负责认证，Memory Service 负责资源授权和 Scope 校验。

### 风险

- LLM 提取非确定性会影响写入一致性，必须版本化 Extractor 并通过 Golden Dataset 回放。
- Scope 与权限错误可能造成严重泄露，必须在数据访问层集中实现并做跨租户测试。
- 记忆积累会增加噪声和成本，需要 Utility、Feedback、归档和 Token 预算闭环。
- 自动形成程序性记忆可能改变 Agent 行为，必须实施风险分级和审核。
- 删除派生数据比删除主记录复杂，必须从第一版保存血缘和操作状态。
- 本地模式与 SaaS 可能产生能力差异，需要 `/v1/capabilities` 和契约测试避免行为漂移。

## 22. 后续输出

设计基线通过审阅后，下一份文档是实现计划。实现计划应按 Phase 拆成可验证的小任务，采用测试驱动方式，先完成领域与存储，再接入模型和向量检索。
