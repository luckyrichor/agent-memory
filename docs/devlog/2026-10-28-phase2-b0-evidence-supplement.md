# B0观测证据补齐


## 2026-10-28T08:24:07.827701+08:00 B0观测证据补齐（局部完成，聚合报告继续暂缓）

由Codex记录，agent-memory@2fae08b，含未提交修改；业务B0@1e9d6f3工作树保持干净。无新增模型调用、未改数据/切分/指标定义/人工原文件。

- `scripts/supplement-b0-evidence.py`累计3次同配置运行的实际HTTP尝试24459次，修正仅统计最后续跑的问题；未知usage不记0。SC8按实际发送文本UTF8字节统计，HTTP响应与传输未知分列，不将第三方发送等同于地理跨境。
- ECD完整负会话开发抽样：8段×3重复，候选误抽37/37；会话重复单元非空18/24，比例75.00%，会话聚类95%区间[0.375, 1.0]。候选均未激活，检索空不代表抽取正确；只代表8段客服样本，非282全量或一般对话。
- 对齐已有LC4/LC5/RL1/RL2/RT10/SC1/SC3观测到目录；LC7仍只正文残留局部证据，不冒充全副本删除通过。
- `scripts/measure-b0-queue-controls.py`在新临时PostgreSQL、非owner/non-bypass角色实测3轮5场景。RL3过期owner修改成功0/9；RL4总任务15，成功9，预设永久失败/重试耗尽死信6。不外推模型故障、进程崩溃或候选提交事务竞态，不称PF。
- E5按既有偏好标签生成16个数据/模式/系统子表。E6逐源验证LongMemEval会话级oracle仅含相关证据会话，剔除无正证据的拒答题、确认未截断；两模式各12实验行/4题，给出与本系统的配对会话bootstrap差值。不是全数据集或句子级oracle。
- 4项相关回归通过，ruff通过、脚本编译和diff检查通过；新增临时PG集成控制真实完成。模型、业务、数据不变，未提交/推送。

证据：`docs/reports/phase2-b0-evidence-supplement-2026-10-27/evidence-supplement.json`、`docs/reports/phase2-b0-evidence-supplement-2026-10-27/queue-controls.json`；完整本地B0 JSON已更新。用户要求未齐项不发，所以没有发送新聚合文件；托管自动交付也加入deferred_until_complete保护，必须显式核验full_aggregate_ready后才允许发出。

仍待：抽取语义逐条对应及相应评审校准、真正目标tokenizer/预算实验、相关度分级标签、通道/参数实验、端到端故障与备份恢复、日志全量覆盖、按系统归因的总成本、独立跨地域PF等。不能因为队列或局部样本通过就宣布全指标完成。压测机准备说明`docs/baselines/b0/load-generator-preparation.md`。阶段2未验收，不进入阶段3；飞书Wiki仍按用户要求暂缓。
