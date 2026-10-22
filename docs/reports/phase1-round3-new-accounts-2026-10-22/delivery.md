# agent-memory 阶段1第三轮：旧池采纳、新密钥预检与增量补量

生成：2026-10-22T13:25:12.140682+00:00；分析源码：`9b11a934e97e5be5e5fe2b8656577585914892c1`；生成时有未提交改动：False。执行工具 Codex；具体 Codex 模型版本未核实。环境：Linux-6.8.0-139-generic-x86_64-with-glibc2.39。阶段1仍未验收，不进入阶段2。

## 执行版本与差异

已完整重读方案 `docs/plans/2026-10-22-agent-memory-interview-plan-v3.md`，SHA256 `06ad7319525c6b0f4eb7333c981b094dd1ed6ec41ae2e5ea1b46009306389418`；原文和署名保留。本轮重读相对上一轮保存的v3原件字节不变；旧v2到v3逐行差异见plan-diff.patch。

v3新增两层记忆、PAL-Set后续可选和自动换型。当前按负责人最新消息执行四项覆盖：旧池不采用时效性筛选；采纳旧池与人工正例并集后补到700；新密钥重新预检；未完成第4批两侧全部作废重做。旧角色表的两个裁判备选按后续至少一个执行，旧DS/MiMo固定组合按已授权换型执行。ECD原件写直接人工标注，实际披露仍为AI草稿加人工确认；旧κ目标不以程序uncertain或本轮通过盲审冒充达标，阶段1仍未验收。原件未被静默改写。

## 当前规模与质量口径

旧池 265 扣除人工错误 3，采纳 262；逐条人工确认 154；重叠 69；去重可靠规模 **347**。其中仅模型标注、抽检整池采纳但未逐条人工确认 193，不得冒称全部人工标签。距700缺 353，距1500缺 1153。

旧盲审 69/72，精度 95.8333%，会话级聚类重采样95%区间 [90.4076%, 100.0000%]；67个会话，1000次，种子42；错误3，压线通过。错误均为临时状态。区间不是额外质量门，也不保证整池最多仅三个未知错误。

旧池不应用时效性筛选。历史筛选仅参考：旧池临时标记 49，识别已知临时错误 3/3，人工正例误剔除 25/154；这些不从旧池或人工正例中剔除。新增池继续任一侧临时即不得keep。合计仅做规模去重汇总，时效性相关误差率按旧池/新增池分别报告，不混报为同一筛选规则。

## 补量目标、预算与库存

基于已完成 400 段、2291 候选、277 共同保留：新增目标 356（含最多三条最终盲审错误的记账预留），初始还缺 79。预留不是统计保证，最终仍由独立72条盲审把关。

条件外推：共同保留率 12.0908%，初始预计还需 654 候选、115 对话（含须重做100段，条件估计额外未用对话15段；固定整批执行时按批舍入）、双侧每请求8条约 164 次；若腾讯侧单条则约 736 次。按历史真实响应均值约 617257 token，不含预检、重试、换型重标和批次舍入；不是实际产出或额度保证。

本轮开始未用库存 892 段；另有此前已选但未完成的 100 段整批重做。新取样种子 20261029，继承原会话切分，只用BOTH/train且字段完整的未用对话。到达目标或用尽库存即停。

## 新密钥预检

MiMo原始98/100中的两项是无响应连接中断，仅对同两个请求有限重试，原其他104响应不重发，独立修复记录保留；没有重采不合格模型答案。密钥从服务器原配置按secondary账户注入，不写日志、仓库或报告。两家目录HTTP200仅表示目录可读，不代替实际调用。原预检中断后从真实已保存响应恢复，不重发已完成的检查；可能在途无响应的调用单列未知用量。

|渠道账户|标注候选/预检版本/输出方式|格式有效/分母|五次一致|关闭思考观测|通过|
|---|---|---:|---|---|---|
|tokenhub-secondary|deepseek/deepseek-flash / annotation-preflight / default|83/100|True|True|False|
|tokenhub-secondary|deepseek/deepseek-v4-flash-vision-exp / annotation-preflight / default|0/0|False|False|False|
|tokenhub-secondary|deepseek-v4-flash-202605 / annotation-preflight / default|0/0|False|False|False|
|tokenhub-secondary|deepseek-v4.1-flash-1017 / annotation-preflight / default|96/100|True|True|False|
|tokenhub-secondary|hunyuan-role-latest / annotation-preflight / default|100/100|True|True|True|
|tokenhub-secondary|hy4-preview / annotation-preflight / default|96/100|True|True|False|
|ark-secondary|deepseek-v4-1-flash-261017 / annotation-preflight-retry / default|0/0|False|False|False|
|tokenhub-secondary|deepseek/deepseek-v4-flash-vision-exp / annotation-preflight-retry / default|98/100|True|True|False|
|tokenhub-secondary|deepseek-v4-flash-202605 / annotation-preflight-retry / default|99/100|True|True|True|
|tokenhub-secondary|deepseek-v4.1-flash-1017 / annotation-preflight-structured / json_schema|100/100|True|True|True|

格式门槛仍为至少99/100；五次一致指label与temporal判定一致，不是理由逐字节一致。100个不同虚构输入只验证格式，不作质量证据。未通过者不能进入本轮标注组合。方舟新增账户实际调用返回404，已存错误码ModelNotOpen，不是余额不足结论；未自行开通模型、充值或修改计费。

## 完整新增批次

|批次|模型组合|对话|候选|共同保留|临时标记|引用无效|结构无效|
|---|---|---:|---:|---:|---:|---:|---:|
|0|deepseek-v4-flash-202605 + hunyuan-role-latest|100|585|77|79|54|1|
|1|deepseek-v4-flash-202605 + hunyuan-role-latest|100|567|78|95|81|7|
|2|deepseek-v4-flash-202605 + hy-role|100|571|58|87|77|5|
|3|deepseek/deepseek-v4-flash-vision-exp + hy-role|100|568|64|57|80|12|
|4|deepseek-v4.1-flash-1017 + hunyuan-role-latest|100|558|56|69|64|19|
|5|deepseek-v4.1-flash-1017 + hunyuan-role-latest|100|557|78|62|72|16|

新增完整冻结 600 段、3406 候选，合格去重共同保留 **409**；原始共同保留 411，历史/内容重复/调试排除 8（全候选分母）。新增目标达成=True；库存未用 792。新增采纳仍为0，当前可靠规模仍为347。

本次关闭=True；阻塞（null表示未记录阻塞）：null。旧第4批两侧结果不拼接、不缓存重放；新批次失败时整侧换型重做，已完整冻结批次保留各自来源。

补量已完成，独立盲审导出 72 条/69 会话，新种子20261030，历史审核/开发/最终/调试条目重叠0。原八列、原source JSON、人工两栏空白、不透明编号、顺序打乱；审核表SHA256 `1c26fb5f8c4fcdfd4de00edf62d893c85458c17f395ec634572024bf7491ca46`。等待负责人核对，错误不超过3条才采纳新增池；通过且最多三错时并集记账规模至少 753，目前不能宣称已达标。新池精度与区间待人工回填。

临时标记、引用无效、结构无效可重叠，不相加；程序拒绝为uncertain不当作模型语义标签算κ。标签仍经原精确source_id、user角色和原话子串校验。

## ECD负样本小金标准


标注方式：**AI 草稿加人工确认**，不是人工独立标注；Agent未改任何人工标签。全表120段：无应记内容108段（90.00%，分母120）；有应记内容7段；不确定5段单列，不计正负。

冻结非人工字段逐项核对一致，旧120表未覆盖。108段作为已确认负样本小金标准；7段正会话不自动折算为7个DuLeMon记忆点。不代表ECD总体分布，尚未用系统运行误抽评测。原文、审核理由与应记内容仅服务器.local/，对外只方法、哈希、指标。

回填SHA256：`95c81861d698d93e453d8c511da12e3470c2608c4368fc5823708f6b7fad5d15`。

## 裁判池：按旧池和新增池分别冻结

|数据表|实际标注厂商|主裁判|备选|备选缺口|
|---|---|---|---|---:|
|old-pool|DeepSeek、Tencent|TokenHub/glm-5.2|TokenHub/mimo-v2.6-flash、TokenHub/minimax-m3|0|
|new-pool|DeepSeek、Tencent|TokenHub/glm-5.2|TokenHub/mimo-v2.6-flash、TokenHub/minimax-m3|0|

答题厂商为ByteDance。旧池时效性筛选未用于采纳，因此参考筛选用过Zhipu不再使旧表排除Zhipu；实际标注仍为DeepSeek/Tencent。新增表按各已完成批实际标注厂商并集排除。目录online不等于通过预检，预下线GLM-5V和已下线型号未恢复；主备尚未做人工校准，不能发布正式阶段2评分。

|渠道账户|裁判候选/预检版本|格式有效/分母|五次一致|关闭思考观测|通用预检|裁判提示词控制|
|---|---|---:|---|---|---|---|
|ark-secondary|glm-5-3-flash-260828 / original|0/0|False|False|False|False|
|ark-secondary|qwen3-14b-20250429 / original|0/0|False|False|False|False|
|ark-secondary|glm-5-2-260617 / original|0/0|False|False|False|False|
|tokenhub-secondary|glm-5.2 / original|100/100|True|True|True|True|
|tokenhub-secondary|mimo-v2.6-flash / original|98/100|True|False|False|True|
|tokenhub-secondary|minimax-m3 / original|100/100|True|True|True|True|
|tokenhub-secondary|mimo-v2.6-flash / transport-repair|100/100|True|True|True|True|

## 用量、测试与复现

仅本轮已知POST 1356，响应报告token 2265432，缓存重放 0 不算新调用；另有中断可能在途、usage未知 8 次，不当作0费用。旧轮用量保留在历史报告，不重复算成本轮。未查询余额、未充值、未开后付费、未修改用量上限。

全量门禁：pytest 432 passed/18.35秒，ruff通过，strict mypy通过，foundation零泄漏/零删除命中门通过。原日志validation.log。

复现汇总：`uv run python scripts/prepare-new-account-round.py`；`uv run python scripts/report-new-account-round.py`。真实运行使用`with-llm-account.py tokenhub-secondary .venv/bin/python scripts/run-temporal-batch-cohorts-v6.py`；已有冻结目录不覆盖，失败历史不删除。原始数据、模型响应、审核映射仅服务器.local；公开仅方法、哈希、指标。

## 未完成与范围

- 新增盲审等待真实负责人回填，通过前不计新增可靠规模；阶段1没有自动验收。

- 裁判人工校准未做；技术池可用export-new-account-judge-pools.py导出到运行入口，run-judge-table.py支持显式--policy及old-pool/new-pool；未校准的主备仍由原加载器硬拒绝正式评分。缺口按表如实保留。

- 完整负样本会话数量与占比双闸门未共同确认；ECD系统误抽评测未做。

- 中文查询三类程序构造题仍为“流程验证，不作质量证据”，阶段2单列；不以高分证明真实中文质量。

- 其他阶段1历史证据（基准导入召回、查询、合成审计）沿用原冻结报告，本轮未重跑；见上一轮交接及第三轮收尾报告。没有进入阶段2或处理其他项目。
