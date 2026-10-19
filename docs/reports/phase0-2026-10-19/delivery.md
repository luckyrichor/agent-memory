# agent-memory 阶段 0 交付报告

生成日期（北京时间）：2026-10-19；执行：Codex（具体模型版本未核实）。
代码：`1e9d6f3b25b58c85792344000d7e1b5a71a79737`；采样/验证前工作树：干净。

## 结论

阶段0的修复与核实已形成工程交付，等待负责人及独立复核。方案第13节要求验收后再进入下一阶段，因此本次未启动阶段1。B0标签只冻结修复后源码，不表示阶段2全指标基线已测完。

| 检查 | 结果 |
|---|---|
| 全量pytest | 234通过，失败0，错误0，跳过0 |
| Ruff | 通过 |
| strict mypy | 68个源码文件通过 |
| Foundation | 8/8，租户泄漏0，删除命中0 |
| 锁文件漏洞扫描 | 19条报告项→0；去重公告18→0 |
| 外部运行时模型 | 调用0次，token 0 |

所有数字由本脚本生成，原始日志、扫描JSON及环境指纹同目录保存；漏洞扫描仅表示该时点该服务对锁定依赖的已知公告，不表示不存在其他漏洞。开发AI自身用量不可得，不计入运行时模型台账。

## 六项处置

1. InvalidScope：原入口无映射，现返回422/INVALID_SCOPE和关联request_id，不回显异常内容；新增缺workspace等API回归。
2. foundation_runner：逐case捕获普通Exception，只存异常类型/失败码且继续其余case；CancelledError/系统退出不吞掉，失败退出码非0。
3. 事件接口：确认原HTTP只收tool.result。新增conversation.message，payload为user/assistant角色及受限summary；不允许system角色，不改变scope授权。写入/幂等/隔离经过真实PG验证，规则提取器对非tool事件仍返回空，LLM仍只读取受限且不可信的summary；没有冒称所有对话都自动提取成功。迁移0008_conversation_events仅在临时测试DB执行；有对话数据时拒绝有损降级。
4. 租约时钟：原claim/renew/succeed/fail接受应用时间，现用PG clock_timestamp()；领取按DB筛选，拿锁后再次读wall clock，避免事务开始时间过期。Outbox→job、重建和admin调度也用DB时间。内存适配器继续可注入时钟用于领域单测。快/慢机器时间、事务内过期、旧owner不能提交已验证。
5. 资源边界：整体请求体1048576字节（Content-Length与实际流双重检查），缓冲后再解析/落库；查询、向量、事件条数/深度等上下界见report.json，版本offset现有限制。未引入索引/缓存/重排等优化，也不称完整抗DoS系统。
6. 锁文件：扫描前后全组冻结requirements与原始公告保留。升级PyJWT/urllib3及开发测试工具pytest/pytest-asyncio；测试工具跨主版本是为修复已知公告，完整回归已覆盖。详见audit-before.json、audit-after.json及uv.lock差异。

## 复现

```bash
uv sync --all-groups --frozen
uv export --frozen --all-groups --no-emit-project --no-hashes --format requirements-txt > .local/requirements.txt
uv tool run pip-audit -r .local/requirements.txt --disable-pip --no-deps --format json --output .local/audit.json
uv run python scripts/phase0-evidence.py --output .local/reproduce-phase0 --audit-input .local/phase0
```

最后命令复跑四道门与临时数据库指纹；audit-input须提供前后审计JSON与requirements原件，可复制本报告目录的四个文件后使用。Docker只在tx运行，不接触持久化业务DB。源码/脚本/锁文件散列在report.json；原始附件保持作者署名及字节内容。

## 尚待验收

负责人验收与独立复核抽查两条开发记录尚未完成，不能编造成已通过。下一阶段的模型预检、数据集下载、κ校准、指标框架及全指标B0未做；无生产部署、无ANN索引或性能提升声明。应用时钟仍可用于非租约业务审计/事件occurred_at，未宣称全系统时间源统一。
