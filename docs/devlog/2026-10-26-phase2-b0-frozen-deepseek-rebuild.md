# 阶段2：冻结DeepSeek+腾讯向量重新建立B0

- 任务：负责人2026-10-26新方案及消息om_x100b62c56df1b8b0ce44568e5c1acc0；更新方案、诊断零检索、预检固定模型、估向量量并重建、全组重跑后新抽300。
- 原理：B0业务源码仍固定1e9d6f3；以配置身份区分新旧结果。冻结请求/观察到的DeepSeek型号，拒绝其他型号或Ark渠道；新库新向量数据避免跨空间拼接。没有靠激活candidate修分。
- 实现：新增b0_frozen约束；ModelIO加入版本/预算守卫与按角色允许渠道；表级裁判备选完整重判，保留无效结果；新校准种子/ID只来自新组。单条完整上下文会话从现有SDK/worker导入，旧结果和向量均不复用。原提示词、指标、切分、验收线不变。
- 涉及文件：`scripts/run-b0.py`、`scripts/start-b0-managed.py`、`scripts/preflight-b0-policy.py`、`scripts/summarize-b0.py`，新约束/诊断/预算/证明/报告/收尾脚本及相应单元和无真实网络集成回归。
- 依赖/环境：Python3.12与uv锁文件；原FastAPI/SQLAlchemy/PostgreSQL+pgvector；不新增模型SDK，使用既有httpx，测试用已有Docker。实际环境指纹由full-run/environment.json生成。
- 执行助手：Codex，具体执行模型版本未核实；本轮实现与报告为助手修改，原方案及验收条件由负责人给定，尚未人工验收。
- 运行模型：DeepSeek官网deepseek-v4-pro用于抽取和答题；TokenHub Kinfra0.6b原生1024；GLM5.2主裁判、MiniMax3备选；MiMo两Key402后，MiniMax作独立条件下的整批参照。实际模型ID、请求参数、提示词哈希与每次输入输出记录，原文只私有目录。
- 数据：阶段1冻结开发投影，原会话切分和源哈希不变；固定sample规划1560实验行，含三次重复与四组、两模式；测试集未运行。三类程序题仅流程验证、ECD只客服领域，不冒称真实通用能力。
- 运行：执行报告提供已执行的一条托管命令，当前unit为agent-memory-b0-frozen-20261026-v1.service，不要重复启动；入口参数数据/模式/配置/指标仍传给同一run-b0.py。
- 预诊断：每会话旧全链路产出/映射/active/检索分别统计；6640映射记忆全部非active，被过滤而非都没抽到。新轮继续记录该缺口，不修改业务。
- 验证：460 passed in45.79s、ruff、strict mypy、foundation通过，外加24行真实新配置小样均有效。报告数字脚本生成，见preflight-and-pilot.json、verification.json、vector-budget.json。
- 用量：小样187次，逐角色token与缺失usage保留；一次向量ConnectError有限重试恢复。完整向量预算66293，是计划余量，不查余额；费用折算未做。DeepSeek额度充足是负责人确认，不冒称API余额实测。
- 问题：原Ark停用；额外向量精确一致性门槛已纠正；Kinfra原生接口不接dimensions；MiMo不可用；一次备选预检网络失败保留后整轮重新探测通过；重试只针对传输错误，不重抽语义/格式失败以挑通过。
- 风险/代价：全组重算资源增加，外部供应商静默权重变化不可验证；同厂商Gold偏差必须披露；O10无法取得新公平Ark对照，旧数据只探索。候选未激活导致full系统检索仍可能为0，这属于B0缺口。
- 当前/遗留：整组正在跑，新300只在全组完成后生成并等人工；主备校准、稳定性、其他观察适配器和独立PF未完成，阶段2未验收，不进阶段3。飞书首次发布方案待确认，尚未同步。
- 代码：基于仓库2fae08b加未提交修改；本轮未提交/推送。源码私有快照sha记录在source-snapshot-manifest.json；评测业务源码标签不覆盖。

## 当场事件记录

| 实际读取时间 | 事件 | 结果 |
|---|---|---|
| 2026-10-26 05:51:51 EDT | Codex核对预检、真实小样、回归并确认整组unit | 单一DeepSeek/腾讯配置运行中；新校准表未生成 |


## 2026-10-26T21:10:18.757947+08:00 候选确认路径补充核查

由 Codex 记录。冻结业务源码 agent-memory@1e9d6f3；评测工具基于2fae08b加未提交修改。

B0-CANDIDATE-ACTIVATION-MISSING：候选记忆无自动生效路径；冻结B0也未实现将原候选确认转为active的公开接口或流程。

公开 restore 只允许 archived→active；候选与 needs_review→active 均被冻结状态机拒绝。POST /v1/memories 创建新的 memory_id，不能作为原候选批准流程。历史文档提到“独立提取批准路径”，但实现只有候选落库，不能据文案宣称已实现。没有正式路径，所以不追加“确认后”实验，值保留 null；不改状态、不重建替代记忆、不改业务代码。

验证：`uv run python scripts/audit-b0-candidate-confirmation.py` 使用冻结状态机执行三种转移（candidate/needs_review拒绝，archived允许），并保存 API 声明与源码哈希；不调用模型，不接触运行数据库。证据：`docs/reports/phase2-b0-rebuild-2026-10-26/candidate-confirmation-audit.json`。未来整组聚合报告自动附此缺陷。当前运行PID3596841保持active，未停止/重启。校准表仅整组完成后按新结果抽样。

飞书待同步：用户本次明确“暂不写飞书”，仅更新本地交接与报告，不创建或修改Wiki。


<!-- frozen-b0-closeout:c5bb4d57e991be34225d -->
## 2026-10-26T22:15:40.142447+08:00 新配置B0运行收尾

由Codex记录，agent-memory@2fae08b，含未提交修改。状态runtime_quota_paused，聚合实验行1512，新校准表0行。证据`.local/phase2/b0/frozen-deepseek-20261026-v1/full-run/aggregate/report.json`。阶段2未验收，PF、负责人校准和缺失观察适配器仍需后续完成，不进阶段3。原始答案/对话不写入此记录；飞书同步按用户要求暂缓。


## 2026-10-27T08:33:52.116549+08:00 DeepSeek额度恢复后同配置续跑

由Codex记录，代码基于agent-memory@2fae08b加未提交修改，业务B0@1e9d6f3不改。官网最小探测HTTP200、响应deepseek-v4-pro，共9token；原402暂停记录保留。新运行`.local/phase2/b0/frozen-deepseek-20261026-v1/recovery-run-1`，unit`agent-memory-b0-frozen-20261026-recovery-1.service`。仅resume_roots不同，其余冻结配置逐字段严格相等；旧混用结果仍禁用。复用完整数据/会话检查点，未完成会话重新抽取与建库、仅上下文哈希一致才复用答题判分。原向量尝试9249累计进入66293上限，不重新给预算。新300表仅整组结束后生成，用户仍要求暂不写飞书。

修改：b0_frozen.py允许严格同配置恢复，run-b0.py累计父运行向量尝试；新增配置一致/变更拒绝回归。验证2条冻结策略测试通过、ruff修复导入后通过、strict mypy单文件通过；最初探测本地代理缺socksio未发请求，随后与运行客户端一致使用trust_env=False完成探测。无模型切换、无业务优化、无提交推送。


<!-- frozen-b0-closeout:e7baeb120a99d26e929d -->
## 2026-10-27T09:45:51.106601+08:00 新配置B0运行收尾

由Codex记录，agent-memory@2fae08b，含未提交修改。状态runtime_quota_paused，聚合实验行1512，新校准表0行。证据`.local/phase2/b0/frozen-deepseek-20261026-v1/recovery-run-1/aggregate/report.json`。阶段2未验收，PF、负责人校准和缺失观察适配器仍需后续完成，不进阶段3。原始答案/对话不写入此记录；飞书同步按用户要求暂缓。


## 2026-10-27T13:07:47.592032+08:00 腾讯向量同型号切换已授权密钥后续跑

由Codex记录，agent-memory@2fae08b加未提交修改；业务B0@1e9d6f3不改。上次续跑于1552/1560条准备结果因TokenHub向量secondary HTTP402（401008）暂停，已有1512条判分；并非DeepSeek再次不足。今日实测：DeepSeek固定型号200；同一向量型号secondary仍402、primary返回200/原生1024维；GLM与MiniMax在secondary均200，primary均402（不采用）。仅向量密钥切primary，其他角色不变。

本轮`.local/phase2/b0/frozen-deepseek-20261026-v1/recovery-run-2`；unit`agent-memory-b0-frozen-20261027-recovery-2.service`。恢复校验只允许TokenHub已授权primary/secondary槽位互换，固定配置的型号、数据、提示词、裁判池、种子和预算仍须一致，不采纳旧混用结果。父运行累计向量HTTP尝试11880，仍共享66293总上限。检查：冻结策略2测试通过（含未知密钥/配置变更拒绝）、ruff通过、mypy单文件通过、探测原始请求响应仅私有目录。新300仅整组完成后导出。飞书按用户要求暂缓，无提交推送。


<!-- frozen-b0-closeout:36798487fe32acba0243 -->
## 2026-10-27T13:56:54.798806+08:00 新配置B0运行收尾

由Codex记录，agent-memory@2fae08b，含未提交修改。状态paused_for_owner_calibration，聚合实验行1560，新校准表300行。证据`.local/phase2/b0/frozen-deepseek-20261026-v1/recovery-run-2/aggregate/report.json`。阶段2未验收，PF、负责人校准和缺失观察适配器仍需后续完成，不进阶段3。原始答案/对话不写入此记录；飞书同步按用户要求暂缓。


## 2026-10-27T18:22:48.989403+08:00 负责人300条裁判校准

由Codex记录，agent-memory@2fae08b加未提交修改。人工300标签核验/冻结字段比对通过，原文件SHA256已记录。主裁判与备选均为第1轮冻结提示词；备选复用同批完整cross-reference，非独立第二模型。 glm-5.2：n=300，准确率0.950000，κ=0.897260，门槛通过=True。 minimax-m3：n=300，准确率0.976667，κ=0.951844，门槛通过=True。 同批100×3新判分完成=False。报告`docs/reports/phase2-b0-owner-calibration-2026-10-27/calibration-report.md`；不外发原文/人工标签/理由。阶段2未验收，PF与缺失指标仍待完成，不进入阶段3；飞书Wiki按用户要求暂缓。


## 2026-10-27T18:23:06.711901+08:00 负责人300条裁判校准

由Codex记录，agent-memory@2fae08b加未提交修改。人工300标签核验/冻结字段比对通过，原文件SHA256已记录。主裁判与备选均为第1轮冻结提示词；备选复用同批完整cross-reference，非独立第二模型。 glm-5.2：n=300，准确率0.950000，κ=0.897260，门槛通过=True。 minimax-m3：n=300，准确率0.976667，κ=0.951844，门槛通过=True。 同批100×3新判分完成=False。报告`docs/reports/phase2-b0-owner-calibration-2026-10-27/calibration-report.md`；不外发原文/人工标签/理由。阶段2未验收，PF与缺失指标仍待完成，不进入阶段3；飞书Wiki按用户要求暂缓。


## 2026-10-27T18:30:34.197735+08:00 负责人300条裁判校准

由Codex记录，agent-memory@2fae08b加未提交修改。人工300标签核验/冻结字段比对通过，原文件SHA256已记录。主裁判与备选均为第1轮冻结提示词；备选复用同批完整cross-reference，非独立第二模型。 glm-5.2：n=300，准确率0.950000，κ=0.897260，门槛通过=True。 minimax-m3：n=300，准确率0.976667，κ=0.951844，门槛通过=True。 同批100×3新判分完成=True。报告`docs/reports/phase2-b0-owner-calibration-2026-10-27/calibration-report.md`；不外发原文/人工标签/理由。阶段2未验收，PF与缺失指标仍待完成，不进入阶段3；飞书Wiki按用户要求暂缓。
