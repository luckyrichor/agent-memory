# W8 M7 / W9 M5 验收（Codex，2026-10-07 北京时间）

## 提炼器

`LLMExtractor` 实现既有 MemoryExtractor Protocol；ExtractionWorker 算法未改。
dispatch/work 均通过同一个配置工厂选择提炼器，版本包含模型 ID；切换模型时
必须先处理旧版本任务，不能用新模型冒充旧版本提炼器。

配置使用 MEMORY_EXTRACTION_ENDPOINT / MODEL / TOKEN / TRUST_ENV。
TOKEN 使用 SecretStr；私密配置存 `.local/ark.env`，不提交。CLI 从环境读取，
运行两个进程时必须加载同一组变量；当前没有新增常驻 API 或 worker 服务。

真实验证模型为 `doubao-seed-2-0-mini-260428`，协议是 Ark Chat Completions。
[官方模型列表](https://docs.volcengine.com/docs/82379/1553576?lang=zh)与
[官方 Chat API 示例](https://docs.volcengine.com/docs/ark/deep-thinking?lang=zh)用于核对协议。
先测 lite 模型遇到 HTTP429 SetLimitExceeded，旧 flash 模型返回404；
mini 实测200，不能据 lite 的限制断言所有文本模型不可用。

- 仅发送4000字符以内的 summary 和事件类型，不发送任意 payload、权限或 scope。
- 模型只允许返回最多3项 content；尝试返回 scope/authority 的响应无效，回退规则。
- 候选保留服务端事件 scope，authority=AGENT_INFERENCE，verification=UNVERIFIED。
  PostgreSQL 中状态为 candidate，不自动升级为有效知识。
- 输入与输出检查常见密码/密钥标记、邮箱、中国手机号；命中拒绝产生候选。
  这是明确模式的防护，不能保证发现任意编码、混淆或所有个人信息。
- HTTP故障、超时、格式错误回退 CodingFailureRuleExtractor；敏感输入先拒绝，
  不经过回退写入候选。只输出稳定原因码，不输出异常或模型正文。

真实端到端验收：独立临时 PostgreSQL → 事件/Outbox → 原 worker → 真实模型
→ candidate/evidence/job 原子落库。两条非 build/test 事件通过，一条敏感样例拒绝，
另一租户读到0条。报告 `measurements/w8-real-llm-pipeline.json`。
失败模型的安全回退也有固定 HTTP401/429/500 测试，CI不依赖线上模型。

```bash
sg docker -c 'MEMORY_EVAL_REAL_EXTRACTION=1 uv run pytest tests/integration/test_llm_pipeline.py -q'
uv run python scripts/probe-extraction.py
```

## 基线对比

同一 PostgreSQL、应用身份/RLS、语料、查询、向量模型、Top1，对比：
No Memory 不提供记忆；Naive Vector 只对所有历史版本做向量排序；系统使用真实
PostgresCandidateProvider + MemoryRetriever，过滤当前版本和生命周期并融合召回。
朴素基线仍有同样的租户隔离；没有人为给予它跨租户访问权限。

三个预先固定的合成生命周期故障：有效知识、更正后的旧版本、删除后的旧记忆。
M7 adapter 通过固定 JSON 响应产生学习候选，再显式记忆写入模拟用户确认。
这里的固定响应不是 CodingFailureRuleExtractor，不依赖线上文本模型漂移。
真实向量另测 Ark `doubao-embedding-vision-251215` 1024维。

结果：No Memory 0/3，Naive Vector 1/3，系统3/3。两组报告在 measurements/。
这些案例刻意包含过时/删除知识，查询接近旧知识；不能推导一般语义检索胜率，
也不能推导真实 LLM 自动修复代码的收益。故障动作只经固定白名单映射到夹具的
include路径，再实际运行g++编译与二进制执行；无记忆时缺header，旧知识选择了
不兼容的依赖API。x86/arm64只是夹具目录标签，不进行交叉编译，不执行检索到的代码。
这是可复现的工程初验，更大规模任务、真实用户工程与统计显著性仍需另做。
基线验收需要本机有g++；CI固定提炼和向量响应，不需要真实密钥。

```bash
sg docker -c 'uv run pytest tests/integration/test_baseline_comparison.py -q'
sg docker -c 'MEMORY_EVAL_REAL_EMBEDDING=1 uv run pytest tests/integration/test_baseline_comparison.py -q'
sg docker -c 'bash scripts/check.sh'
```

来源：agent-memory@c5a067a + 本轮工作树修改；精确源码 SHA256见测量元数据。
