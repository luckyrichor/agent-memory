# agent-memory 阶段2 B0执行交接（进行中，非验收报告）

生成：2026-10-23T15:12:18.184369+08:00；工具源码：87a7da9f25242628281f80a79c4c4b966578a618；B0：1e9d6f3b25b58c85792344000d7e1b5a71a79737。报告生成时是否存在未提交修改：False。业务源码标签未覆盖。

## 当前状态

当前轮：development-sample-v4。阶段2尚未完成，正式质量分数尚未获准，未进入阶段3。旧pro因429/SetLimitExceeded暂停；更换DeepSeek后的新轮因402暂停。负责人明确授权换型后，Ark lite按原标准复验通过，正在新的独立目录运行。失败仅代表相应型号/身份的实际失败，不是所有模型余额结论。

## 方案与数据口径

完整重读：docs/plans/2026-10-22-agent-memory-interview-plan-v3.md，SHA256 `06ad7319525c6b0f4eb7333c981b094dd1ed6ec41ae2e5ea1b46009306389418`。与前轮同文件；本轮负责人约定与文件的出入：
- B0 all metrics dev only; test deferred to final evaluation
- Independent cross-region Linux cloud load generator replaces Mac
- Phase1 accepted union756 and classifiable conversations828, ECD negative282; counts are global not dev counts
- Old pool no temporal screen; new pool screened; owner-confirmed AI drafts not independent human labeling
- Judge selection based on actual per-table annotation vendors and >=1 backup; historical role table is not current freeze
- Human calibration and ECD false extraction belong to phase2, not remaining phase1 tasks

数据：冻结全局756记忆点、828个可分类会话，非全部来自DuLeMon；ECD确认负会话282。开发集投影及输入哈希见report.json.frozen_data，不能用全局数冒充开发集分母。ECD为客服领域，不代表一般对话；AI草稿加人工确认，不称独立人工标注。所有原文、问题、答案、私有校准及响应仅服务器。测试集未执行。

## 已执行记录（上下文不等于答题成绩）

| 轮次 | 状态 | 准备上下文行 | 完成答题和判分行 | HTTP尝试 | 向量重放 |
| --- | --- | ---: | ---: | ---: | ---: |
| runtime-pilot-v1 | running or interrupted; inspect process separately | 0 | 0 | 3 | 0 |
| api-pilot-v1 | incomplete_calibration_population | 0 | 0 | 213 | 0 |
| api-pilot-v2 | incomplete_calibration_population | 24 | 24 | 593 | 0 |
| development-sample-v1 | runtime_quota_paused | 240 | 0 | 3741 | 0 |
| development-sample-v3 | runtime_quota_paused | 84 | 0 | 393 | 92 |
| api-pilot-lite-v1 | incomplete_calibration_population | 24 | 24 | 156 | 60 |
| development-sample-v4 | running or interrupted; inspect process separately | 60 | 0 | 227 | 198 |

每轮角色、型号、HTTP、已报告token、未知usage与未配对请求见JSON；关机status可能早于晚到usage，最终以完整台账核算。价格和余额未验证，不以未知usage当0。旧操作小样有基线实现问题，不能用于正式对比；旧上下文预算显式100000，不是B0默认2000。

## 框架纠错与对比边界

朴素向量直写库覆盖全部原文分块，包括被系统策略拒绝的块；余弦一个通道，无过滤、词法或融合。系统派生向量走冻结embedding worker。真实向量的校验重放有单独台账，历史token不算新消耗，零重放延迟不冒充系统性能或缓存收益。旧抽取输出不拼接到新型号。系统candidate不偷偷激活。全文超限截断只在明确超限错误时执行，从最旧端截断并记录序列化字符比例；真实超限分支尚未验证。

## 指标、重复与失败案例

完整目录的未测值、样本量及CI均保留null，见metric_coverage；没有观测不写成0分或通过。当前尚无完整新模型质量对比、分题型最差项、三次关键结论波动及20个正式失败案例，不把未校准试跑凑成最终报告。三类程序构造题只作流程验证，与真实中文分开。历史真实tokenizer诊断有60次请求，其原日志末尾哈希不是选中快照哈希，限制已单列。

程序构造正确性控制（完整观测见JSON，不能外推一般对话质量）：LC5穷举非法转换均拒绝；RL1/RL2并发控制没有重复/丢失更新；SC1已知ID跨租户、SC3空权限控制没有成功越权。均仅有限夹具。LC7三轮逻辑删除仍各有2个正文版本，不能声称删除完整性通过；向量、事件、备份尚未全查。未优化系统或物理清理。

## 校准与压测

主裁判与备选只有技术预检，尚未人工校准。尚未交付完整300条人工空栏盲校准表，κ、准确率、假阳性与100条三次稳定性均未验证。独立压测机准备说明已发本群；在负责人提供机器前不执行公网PF。两端指纹、带宽、RTT、发压端70%无效判据、客户端/服务端耗时分开等均待实测，不能声称压测机可释放。

## 测试与剩余工作

框架检查：pytest 447 passed in 27.04s；ruff、strict mypy、foundation结果见JSON。检查对象为测量工具当前版本，不是把当前业务代码当B0；原B0另有冻结源码测试记录。
- all requested metrics and missing observation adapters; undefined values remain null
- complete new-model sampled answers and grading, repeats and >=20 categorized failure cases
- private 300-row calibration export and owner labels; backup judge calibration also pending
- judge-derived metrics cannot become formal before calibration
- independent cross-region load host and PF1-PF10; preparation delivered to group
- full-context real over-limit branch not yet exercised; offline branch regression is not live evidence
- phase2 owner acceptance; no automatic phase3
