# M3 Embedding worker

最后更新：2026-10-01；Codex；agent-memory@5b9ee55 + 未提交修改。

每个不可变 MemoryVersion 插入后，SECURITY INVOKER 数据库 trigger 将 embed_memory Job 写进同一事务；API 创建、correct 与提取 worker 共用此路径，不需要在 HTTP 请求中调用供应商。事务回滚时任务也回滚。Job payload 只有版本 ID，正文在执行时经租户 RLS 读取。提取 worker 只取 extract_event，embedding worker 只取 embed_memory。

领取提交后调用 provider（HTTP 超时 10s < 租约 30s），完成时重新检查租约，向量 upsert 与 Job succeeded 同事务。进程崩溃后租约到期重领；失败指数退避，五次失败持久 dead，任务不删除。用户用新 rebuild key 可重新排队；同 rebuild key 重放无重复 Job。provider 错误正文不能写进日志。

```bash
uv run python -m agent_memory.workers.embedding work --tenant-id <uuid> --worker-id e1 --once --fixture
uv run python -m agent_memory.workers.embedding rebuild --tenant-id <uuid> --version-id <uuid> --key <unique-request-key>
```

`--fixture` 仅验证管道，生成确定性 1024 维夹具向量，**不具备语义召回能力，不是已接入真实模型的证据**。实际 HTTP provider 从 MEMORY_EMBEDDING_ENDPOINT / MEMORY_EMBEDDING_MODEL / MEMORY_EMBEDDING_TOKEN 配置供应商，协议为 POST {model,input} → data[0].embedding；历史初验使用MockTransport；现已增加ark协议并完成真实模型验证。维度固定 1024，非法长度/NaN/Infinity 均失败重试。

迁移不会跨租户扫描历史版本：原有版本需按 tenant/version rebuild，新版本自动排队。未做后台批量重建管理员接口、多模型并存、全文/向量检索、物理清理执行者。被删除的记忆已禁止正常读取，但派生向量清理仍属已知待办。

内存 EmbeddingBackend 支持无数据库用例测试（enqueue 模拟版本提交）；生产版本写入由 Postgres trigger 确保事务调度。测试覆盖重启重试、过期租约恢复、旧 owner 不能写、重建幂等、RLS 与回滚。
