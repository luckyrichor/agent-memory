# 阶段1：长期时效性与真实审核接入

目标：按最新版方案第5节长期记忆口径补齐时效性判断，同时保留原v3引用校验；不实现短期TTL，不进入阶段2。

Codex编写实现与脚本，负责人提供方案、规则及真实审核；执行模型名以元数据为准，不编造CLI模型版本。方案与开发指令保留在docs/plans和任务关联message_id。基础技术Python/uv/httpx/Pydantic，版本见uv.lock；不改数据库。

设计：原265池只做长期/临时筛选，同时带入已有人工正例量化误剔除；不把模型判临时覆盖人工标签。全部真实人工回填先按冻结ID、来源、摘要核对，引用校验仍仅精确验证source_id、用户角色与原话子串，不把程序检查当语义证明。新字段由额外schema承载，不改旧证据响应或旧冻结文件。

失败与处理：HY4部分调用后HTTP402，部分仅保留历史；技术候选严格预检后用Ark GLM整侧重新判断。保留预检失败与调用台账，不调限额/计费。厂商独立约束随数据实际标注/筛选厂商调整。

数据：原archive、来源切分、旧标签均保留；ECD只本地。新来源仅取unused BOTH/train，固定种子、继承会话切分，新候选与原生参照字段隔离；新盲审排除全部历史审核/开发/最终项。种子、模型版本、输入输出哈希、每批计数与用量见自动生成报告，不手填。

运行：`with-llm uv run python scripts/continue-temporal-screen.py`；`with-llm uv run python scripts/run-temporal-increment.py`；`uv run python scripts/report-temporal-phase1.py`。ECD接入一次性：`uv run python scripts/ingest-ecd-owner-review.py`，已有输出禁止覆盖。完整测试`bash scripts/check.sh`，原始门禁日志在私有temporal-v1目录。

代价：时效性减少产量并存在误剔除；屏蔽真实人工标签后评估，不按这些已知答案反复调提示词。新增池未经过负责人独立盲审前不采纳；旧池时效性结果待负责人决定。裁判主备与人工校准仍有缺口，完整负会话闸门未通过本次接入自动宣称满足。ECD接入不是系统误抽评测。

数字与来源提交：对应docs/reports/phase1-round3-temporal-2026-10-22/report.json，未完成项同表；只有负责人可验收阶段1。
