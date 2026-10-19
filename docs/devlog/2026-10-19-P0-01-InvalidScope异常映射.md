# P0-01：InvalidScope异常映射

## 任务与目标

方案§2.阶段0.1；SC3/错误契约。用户任务原文：“把这个文档放到agent-memory项目下，然后根据这个文档继续开发。”执行指令依据为原方案§2阶段0六项及§13逐阶段交接。具体范围见[tasks-phase0.md](tasks-phase0.md)。

## 设计思路与怎么写的

API创建记忆时构造MemoryScope，域层抛InvalidScope，原HTTP没有处理器。选择保留领域验证，边界仅映射稳定422/INVALID_SCOPE，不用全局吞所有ValueError避免掩盖程序错误。

改动入口：src/agent_memory/api/app.py；tests/api/test_memory_api.py。技术栈版本取交付report.json/environment；数据库pgvector/pgvector:pg16镜像digest、实际PG与vector版本由脚本查询。没有新增ANN索引或质量/性能优化。

## 输入、输出与验收

输入为已核实的原始源码及合成回归夹具；输出为修复、测试、环境指纹和阶段0报告。判据：缺workspace、非法scope组合的HTTP请求应返回422，错误request_id与响应头一致，无异常正文。

## 代码AI与运行时模型

实现和测试由Codex编写；具体开发模型版本未核实。任务说明存本目录tasks-phase0.md，目标来自用户原方案，负责人尚未审阅/修改这些代码。运行时不调用Ark或腾讯模型；测试使用本地fixture/mock。没有运行时模型提示词变更或新增付费模型调用；开发AI自身token/费用不可得，不编造。原始用户方案作者署名保持。

## 数据与复现

只用仓库合成测试夹具，不下载真实用户记忆或公开基准，不改变评测切分/标签。源码与夹具哈希见[阶段0report.json](../reports/phase0-2026-10-19/report.json)；本文不抄写数字。

仓库根执行：`uv sync --all-groups --frozen`，然后`uv run python scripts/phase0-evidence.py --output .local/reproduce-phase0 --audit-input .local/phase0`。审计输入的四个原件可从公开交付报告目录复制，或按交付命令重新扫描；脚本拒绝覆盖已有输出。Docker只跑tx。

## 结果与失败处理

[完整阶段0交付](../reports/phase0-2026-10-19/delivery.md)和原始gate日志/扫描JSON是数字事实源。原始版本先全量回归，再逐项修复后验证。全量首次遇到迁移回滚共享库冲突，保留拒绝有损降级保护，改独立临时库并补覆盖；旧PG租约测试原先靠传入未来应用时间模拟过期，现改操纵临时DB时间字段，领域单测仍可注入时钟。没有删除安全断言来过门。

## 代价、风险与未做项

身份仍来自JWT，scope权限检查和数据库事务保持；这不是新权限系统。

本次只做阶段0。阶段1评测框架、公开数据导入、模型预检及裁判标注未做；阶段2全指标B0未测。本文引用的B0仅修复后源代码标签，不称已完成全指标报告。

## 提交与评审

代码由B0标签固定，原始基线为1e2730c；精确执行提交见阶段报告source.commit。负责人验收待完成；按方案需由未参与实现者抽查两条记录复现，目前未完成，不冒充独立复核通过。
