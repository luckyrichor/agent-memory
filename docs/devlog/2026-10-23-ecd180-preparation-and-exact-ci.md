# ECD180预备审核与精确二项区间补充

## 任务与来源

方案§5、§7、§14与负责人最新任务；执行方案 `docs/plans/2026-10-22-agent-memory-interview-plan-v3.md`，哈希 `06ad7319525c6b0f4eb7333c981b094dd1ed6ec41ae2e5ea1b46009306389418`。AI为Codex，具体模型版本未核实；目标与审核标准由负责人确定，本次代码与报告由Codex编写，未冒充负责人已审阅。

## 原理与实现

metrics.py新增双侧等尾Clopper–Pearson：一般情况反演二项尾概率，全成功/全失败采用闭式界；不修改原ratio聚类bootstrap。手算边界、NIST例子、独立尾概率与非法参数均有单测。区间只是补充，不作会话相关性校正，不改变抽检标准。

prepare-ecd180-review-v1.py不读取模型标签文件，保留原八列与JSON逐轮来源、空白人工栏和随机行序；强制指定fresh或unreviewed及负责人决定。fresh模式对原始正确回复配对会话去重、排除全部旧输入，再作固定新种子的均匀水塘抽样，旧切分只追加；unreviewed模式只从旧库未人工核对部分抽样，切分逐ID继承。两者含义不同，负责人确认前未执行任一模式。新抽样种子拟固定20261101；不是已执行事实。

## 复现、环境与结果

`bash scripts/check.sh`；`uv run python scripts/report-ecd180-review-v1.py`。Python `3.12.3`，平台 `Linux-6.8.0-139-generic-x86_64-with-glibc2.39`；无新增依赖，严格检验保持。测试 440、ruff、strict mypy、foundation8/8通过。报告数字由脚本生成。

## 风险、失败与遗留

400段冻结ECD均曾用于模型标注，120段已审；“全新未用”与“继承仅覆盖旧库的切分”需明确追加口径，当前等待负责人选择。原始文本仅服务器私有，不放GitHub，不调用模型，不推断负标签。初次报告分母漏合并独立存储的DuLeMon正会话，被断言拦截后修正。NIST显示值末位的测试误差已按来源精度处理，并直接核对二项概率；未改统计标准。

新增模型调用0、token0。代价为普通CPU检验。阶段1未验收，未进入阶段2；裁判/模型配置及既有人工标签、可靠规模不变。提交以Git历史及正式报告记录为准；负责人审阅结论尚待。


## 2026-10-23 ECD全新预备表已获批并完成（Codex）

按负责人消息 `om_x100b629f278d18a8dd5f2ee1bf3a6fe`，从完整原库 train 的去重匹配上下文纯随机抽样，排除全部已用 400 段（含已审 120 段），种子 20261101，总体 386077，导出 180 段；旧样本重叠为零。stratum只在抽样后计算，分布 `{'no_personal_information_hint': 166, 'personal_information_hint': 14}`，不用于筛选。新切分 `{'test': 126, 'dev': 54}` 只追加，旧文件与旧归属不变。

原八列、完整逐轮JSON与空白人工栏已核验；CSV仅在 `.local/phase1/round3/ecd180-review-v1/sample/ecd180-preparation.csv`，SHA256 `b4105d19c9667d655fe8516a900b754da27ca20d8989a8ffe0c738cd7bd52d39`。同种子独立重跑的CSV、JSONL、扩展切分哈希一致。既有采纳与人工标签注册表未改，模型调用 0，不提前推断新标签。当前负会话 108/648，等待人工确认后按冻结公式重算。

全门 440 passed in 18.24s；ruff、strict mypy、foundation通过。新交接 `docs/reports/phase1-ecd180-fresh-preparation-2026-10-23/delivery.md`，旧等待口径报告保留为历史。方案文件及哈希与前轮一致，负责人追加源池/切分授权的出入已列。未完成：人工确认、负占比通过和阶段1负责人验收；不进入阶段2。
