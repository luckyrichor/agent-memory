# 火山1024维接入与M4真实验收

2026-10-02（北京时间），Codex；来源 agent-memory@462ec1a + 本次工作树修改。测量JSON含实际源文件SHA256及dirty状态。

## 接入

使用doubao-embedding-vision-251215，`/api/v3/embeddings/multimodal`，纯文字对象输入、dimensions=1024，解析data.embedding。[官方协议](https://docs.volcengine.com/docs/ark/multimodal-vectorization-api?lang=zh)。原OpenAI兼容协议仍支持，系统维度统一1024。

Worker和查询API统一配置MEMORY_EMBEDDING_ENDPOINT、MEMORY_EMBEDDING_MODEL、MEMORY_EMBEDDING_TOKEN、MEMORY_EMBEDDING_PROTOCOL=ark。tx直连用MEMORY_EMBEDDING_TRUST_ENV=false。本机`.local/ark.env`存配置和密钥、权限0600；启动前在本机加载，GitHub不含凭据。worker原MEMORY_EMBEDDING_URL须改为MEMORY_EMBEDDING_ENDPOINT。

## 迁移

0004历史迁移保留1536定义，新增0006_embedding_1024。停止应用/worker后由具有跨租户权限的迁移管理员执行：清除派生旧向量、改列为vector(1024)、为每个已有版本排重建任务。记忆正文、版本、权限、生命周期保留；回退也会清向量并排1536重建。禁止截断/补零冒充另一模型的向量。

切换前备份，用同一选定模型worker处理重建任务。重建期间向量通道可能为空，全文/结构化可继续使用；API和worker须同版本同模型一起切换。

tx常驻库原0003、0记忆/0版本，已pg_dump本机备份并升级0006；实查vector(1024)、仍0/0，无存量重建任务。备份`.local/pre-1024-2026-10-02.dump`未进Git。本次没有新增常驻API/worker服务。

## 验收与复现

全量120 tests、ruff、strict mypy56、foundation8/8通过；新增两个租户旧1536向量清理、版本保留、重建排队的迁移测试及Ark协议测试。

真实供应商→持久worker→独立PostgreSQL/pgvector→JWT查询API：5个合成中文记忆，5条语义改写，Top1为5/5；每条lexical=0、structured=0、vector=5，召回来自实际模型向量。其他租户为空，删除后无该记忆命中。原三路/融合解释/分页由全量测试覆盖，M4初验通过。

本机加载MEMORY_EMBEDDING_*后，显式 `uv run pytest tests/api/ark_validation.py -q` 复现，会调用付费供应商；默认测试不调用。只发送合成语料，不发送原有用户记忆。报告见measurements/2026-10-02-ark-retrieval.json，含源文件SHA256与工作树状态。

5个样例是里程碑正确性初验，不是生产召回率；更多语义评测、基线对比、真实提取器仍按M5/M6/M7推进。
