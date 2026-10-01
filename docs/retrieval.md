# W6 / M4 混合检索

最后更新：2026-10-02（北京时间）；Codex。实现与测试来源：agent-memory@ac7712a + 本轮工作树修改。

`POST /v1/memories/search`，SDK `MemoryClient.search(SearchRequest(...))`。请求包含 `query`、可选 `memory_type` / `workspace_id`、`limit` / `offset`；可选 `vector`（1536 个有限值、非零）和对应 `model`。身份仅由 JWT 提供，请求体不允许 tenant_id。无向量时仍可全文/结构化检索。

自然语言查询需要语义向量时，在服务进程配置 `MEMORY_EMBEDDING_ENDPOINT`、`MEMORY_EMBEDDING_MODEL`、`MEMORY_EMBEDDING_TOKEN`。查询模型必须与 embedding worker 的落库模型一致。HTTP provider 超时、失败或返回非法向量时降级到其余通道，响应 `vector_status=degraded`；没有配置则 `not_configured`。本轮未使用线上模型，不能据夹具宣称真实语义质量已验收。

## 召回与解释

- PostgreSQL `simple` 的 `to_tsvector` / `plainto_tsquery` + GIN 索引；没有中文分词器，不声称中文分词质量。
- pgvector cosine 距离，按模型过滤，只关联当前版本的向量；旧版本向量不会参与。零向量 worker 判失败进入重试，历史非法距离不进入候选。
- 结构化通道按类型/工作区过滤、更新时间排序；只有请求显式提供过滤条件才启用。
- 三路先过滤 active、租户、授权工作区、用户 scope，再各取最多 1000 个候选。强制 RLS 仍有效；不先搜全库后过滤。
- 去重后 `score = Σ weight[channel] / (60 + rank[channel])`，全文/向量权重为 1，结构化为 0.25。响应给出 `ranks`、`raw_scores`、融合公式和候选计数；同分用 memory_id 稳定排序。结构化权重较低，避免仅因新近更新而压过向量相关性。

## 统一分页

搜索和 `GET /v1/memories/{id}/versions` 都返回 `items`、`limit`、`offset`、`next_offset`，默认 limit=20，范围 1–100。版本列表按版本号升序；offset 非负。搜索 offset 0–2900，分页对象为至多 3000 个融合候选，非全量记忆库存。最后一页 next_offset=null。请求间发生写入时不提供快照一致性，必要时从首页重新查询。

版本详情用例仍会加载该记忆的历史版本后切片，当前分页约束响应大小，并未优化长版本历史的数据库读取量。Context Builder、证据 packet、冲突抑制、生产级索引性能/模型质量评估尚未验收。

## 验收

实际 PostgreSQL / pgvector、非 owner API 角色：三路可见、得分重算、分页、纠正后旧向量退出、删除退出、跨租户/工作区/用户 scope/needs_review/archive 硬过滤。固定的改写 query 向量验证向量通道能召回关键词不同的原记忆，属于检索流程夹具测试。内存适配器也验证融合/分页/隔离；其词法模拟不代替 PostgreSQL 测试。

本轮四道门：118 pytest passed；ruff 通过；strict mypy 56 文件通过；foundation 8/8，0 tenant leaks / 0 deleted hits。M4 工程实现通过，真实模型的语义改写效果按用户授权暂跳过，M4 不标为全部验收完成。
