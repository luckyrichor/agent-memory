# agent-memory 阶段1：长期记忆筛选与补量交接

生成时间：2026-10-22T08:22:15.379647+00:00；代码：0d8c19a2114224ae6021e5ec283e599ad0f9dc5b；生成前存在未提交改动（含新文件）：True。阶段1仍未验收，不进入阶段2。

执行方案：`docs/plans/2026-10-22-agent-memory-interview-plan-v3.md`；SHA256 `06ad7319525c6b0f4eb7333c981b094dd1ed6ec41ae2e5ea1b46009306389418`。原作者保留，旧版未覆盖。按最新方案及负责人当前任务执行。

## 本轮状态

本次标注尝试已关闭=True；补量目标达成=False；阶段1未验收。完整冻结400段、2291候选；共同保留277条仍未采纳；人工确认正例154条。

不能把当前双模型组合受阻概括为所有模型余额耗尽：本轮DeepSeek侧仍有真实成功调用；腾讯Turbo先遇多候选格式故障，单条修复后再明确返回402。未查询全模型余额；这是已验证候选池当前无法继续配对，不是全目录余额结论。

## 方案变化与口径

- 新增PAL-Set：阶段2之后可选，不计入阶段1金标或召回

- 新增两层记忆设计：阶段1只做长期记忆；短期TTL以后可选，本轮未实现

- 额度不足可自动替换标注模型；受影响侧按冻结批整批重标，旧标签留历史不混用

- 内部旧口径：旧角色表写两个备选，与负责人后续至少一个不一致，按后续至少一个执行

- 内部旧口径：旧角色表仍列DeepSeek/MiMo，实际采用负责人已授权的替代组合，按每批来源记录

- 内部旧口径：原生22/旧711属于历史规模，当前使用真实回填及当前登记，不沿用旧总数

完整逐行差异见 plan-diff.patch。PAL-Set来源内容为负责人方案声明，本轮未另行验证或下载。

## 新盲审与人工正例

精度 69/72 = 95.8333%；按会话聚类，67个会话，1000次重采样、种子42，95%区间 [90.4076%, 100.0000%]。

错误 3 条，上限 3 条，压线通过。错误类型：临时状态误作长期记忆 3 条。置信区间不是新的通过门。

逐条人工确认：此前 85 + 本轮 69，按原item_id去重 154；这些是人工正例，不是整池逐条人工核验。

仅按人工确认规模，到700缺 546；到1500缺 1346。原265池与本轮72重叠，不能再把72加一次。

## 时效性筛选（待负责人决定是否采用）

原池 265，与历史正例合并后仅判时效性的输入 350；模型：deepseek-v4.1-flash-1017, glm-5-2-260617。提示词只新增时效性标准，例子完全虚构，候选不改写。原引用校验器不变。

HY4在完成部分后HTTP402，停止旧侧；替代模型对该侧全部输入重新判定，旧部分不混用。腾讯HY3额度不足；HY-role首轮因普通429未完成预检，后续仅补齐被限流的同一虚构请求，结果见下方资格台账，不混淆格式错误与限流。详见私有switches/ledger。

已知临时错误识别 3/3；人工正确项误剔除 25/154（此前85中 16，本轮69中 9）。

原池时效性剔除 49；人工判错显式扣除 3，两类取并集，不重复扣。筛后拟采纳池 216，其中已人工确认60、尚未逐条人工核验156。如负责人采用且人工标签保持权威，与全部人工正例去重并集为310；当前实际模型池采纳仍为0。早期301仅是216与此前85相加，漏含筛选误剔除但本轮已人工确认的9项，不作为总体可靠规模。

人工确认登记不由模型误剔除自动改写；模型筛选池与人工登记分别保存。没有自行设置筛选通过线。

## 增量批次

源对话库存：补量开始前有1392段未用且字段完整对话；包括未完成/退役尝试在内，按会话ID去重已选500段，尚未选入任何补量批次892段。控制器remaining_unused_dialogues只减完成批，不将其冒称真实未用库存。

每100段固定对话为一个冻结批次；额度切换时当前批受影响一侧整批重标，已完成批保留独立模型来源，不拼接半批。此口径在首个增量批完成前确定，替代此前全部队列重启方式。格式无效条目严格拒绝并记程序uncertain，不删多余字段、不修改响应、不放宽引用校验；程序uncertain不作模型语义判断或一致率证据。时效性剔除为任一侧标临时的条目数，包含本已discard/uncertain项，与引用、结构无效计数可重叠，不应相加。

补量预算基于已完成批次的真实共同保留率，仍是条件外推。预筛池及两侧各8条/请求的旧预算留历史，当前腾讯单条请求另算调用数与token；不能据此推断账户余额。

固定新种子；只用未用过且字段完整的BOTH/train，沿用原候选生成逻辑，原生标签字段不提供给模型。继承原会话切分。新增池在负责人独立72盲审前不计入可靠规模。

|批次|模型组合|完整对话分母|候选|共同保留|临时标记/排除（任一侧）|引用无效（任一侧）|结构无效|
|---|---|---:|---:|---:|---:|---:|---:|
|0|deepseek-v4-flash-202605 + hunyuan-role-latest|100|585|77|79|54|1|
|1|deepseek-v4-flash-202605 + hunyuan-role-latest|100|567|78|95|81|7|
|2|deepseek-v4-flash-202605 + hy-role|100|571|58|87|77|5|
|3|deepseek/deepseek-v4-flash-vision-exp + hy-role|100|568|64|57|80|12|

已完整冻结400段/2291候选，共同保留277；新增目标549未达到，尚缺272。失败的当前批整体排除，实际新增采纳0。阶段性72条审核包仅本地准备、未发出、不作为人工证据；遵守补量完成后再发新增盲审表的顺序，不催本次临时包。

阻塞：{"batch": 4, "model": "hunyuan-turbos-vision-video-20250728", "http": 402, "error_code": "401008", "error_type": null, "cause": "no further qualified independent available candidate in bounded pool"}。已终止本次运行，不是补量完成或阶段验收；有界候选试用结果不代表所有目录型号都不可用。

### 未完成批单侧进度（不计金标）

|批次|模型|候选分母|完成|模型keep经严格校验后|临时标记|证据无效（含结构拒绝）|
|---|---|---:|---:|---:|---:|---:|
|4|deepseek/deepseek-v4-flash-vision-exp|558|558|75|23|3|
|4|hunyuan-turbos-vision-video-20250728|558|371|32|328|39|

预算更正：早期按预筛701池外推原始候选不合适，已退役该估计。当前完整单侧保留79/585；如果另一侧不再损失任何候选，条件乐观外推需4066候选、721对话、约1018次双侧POST。该单侧口径不能当作实际共同保留率或产出承诺；不设新产量质量门。

按已完成批次条件外推：277/2291共同保留，若后续同分布，预计4541候选、805对话、双侧1136次POST产生目标549条；未含重试/换型重标/百会话舍入，不是实际可靠规模。

## ECD负样本小金标准

标注方式：**AI 草稿加人工确认**，不是人工独立标注；Agent未改任何人工标签。全表120段：无应记内容108段（90.00%，分母120）；有应记内容7段；不确定5段单列，不计正负。

冻结非人工字段逐项核对一致，旧120表未覆盖。108段作为已确认负样本小金标准；7段正会话不自动折算为7个DuLeMon记忆点。不代表ECD总体分布，尚未用系统运行误抽评测。原文、审核理由与应记内容仅服务器.local/，对外只方法、哈希、指标。

回填SHA256：`95c81861d698d93e453d8c511da12e3470c2608c4368fc5823708f6b7fad5d15`。

## 裁判池影响

|数据表|实际标注或筛选厂商|答题厂商|当前可调用且合格裁判厂商|主备缺口|
|---|---|---|---|---|
|旧池含时效性筛选|DeepSeek、Tencent、Zhipu|ByteDance|无已验证可用|主裁判缺失，备选缺1|
|新增已完成批|DeepSeek、Tencent|ByteDance|无已验证可用；Zhipu仅满足厂商独立|主裁判缺失，备选缺1|

标注模型逐批列在report.json；Xiaomi、MiniMax、Moonshot仅是未触犯厂商排除的候选范围，不代表预检或实际调用合格。腾讯GLM本轮实际402，Ark GLM本轮用量上限，未以目录online代替可调用证据。

旧池时效性筛选实际用过GLM，因此旧池不能由智谱裁判；新补量若最终仅用DeepSeek/腾讯，智谱在厂商独立性上可用，历史预检也通过，但Ark本轮已SetLimitExceeded，不能称当前可用。原GLM部分补量结果已退役，不混入新批。当前稳定可用主裁判缺失，备用仍缺至少一个；未放宽预检，人工校准也未完成。

## 用量与证据

完整门禁：pytest 430通过/17.93秒，ruff通过=True，strict mypy 98源文件，foundation零泄漏门通过=True。原始日志见validation.log。

当前台账POST尝试 1456；成功响应报告token 5072118。另有6条可能在途、没有最终响应记录；失败或中断无usage不按0实际用量推断，以上为响应报告token而非完整账单。额外替代资格预检台账在tokenhub-pool-qualification目录，单独记录，未混为筛选调用。

替代资格预检已知POST尝试1079次，另2次可能在途，报告token合计924303；普通429与额度故障分开。旧报告不覆盖，Ark历史预检复用不计新调用。各次资格结果见下表及report.json，不与真实人工质量校验混淆。

原始CSV、来源、请求响应、映射、调用台账只在服务器.local/，公开仓库仅方法、哈希、指标。CSV SHA256：`5be99e4f6dcc8eb206fd672880efccb8ad96d45eef9f39a9b207016479e31397`。

重放汇总：`uv run python scripts/report-temporal-phase1.py`；真实筛选入口：`scripts/continue-temporal-screen.py`；多候选旧入口v4已经关闭并保留历史；当前单条请求入口：`scripts/run-temporal-batch-cohorts-v5.py`，候选/提示词/引用校验不变；旧阻塞快照由`scripts/finalize-temporal-completed-batches.py`保留，不覆盖新批。缓存修复后只复用真实响应并重验；修复前实际重复调用仍在事故台账中，不声称没有多计费。

### 技术预检台账（不是人工质量证据）

|组别|模型|格式有效/检查数|五次判定一致|关闭思考检查|技术预检通过|已知新POST|响应报告token|
|---|---|---:|---|---|---|---:|---:|
|原始通用格式|deepseek/deepseek-flash|100/100|True|True|True|105|7455|
|原始通用格式|deepseek-v4-flash-202605|68/100|True|False|False|105|5183|
|原始通用格式|hy-role|55/100|True|False|False|105|4084|
|原始通用格式|hy3|0/0|False|False|False|1|0|
|原始通用格式|hy4-preview|0/0|False|False|False|1|0|
|原始通用格式|mimo-v2.6-flash|0/0|False|False|False|1|0|
|原始通用格式|minimax-m2.7|0/0|False|False|False|1|217|
|原始通用格式|minimax-m3|0/0|False|False|False|1|0|
|限流同题补齐|deepseek-v4-flash-202605|100/100|True|True|True|32|2272|
|限流同题补齐|hy-role|100/100|True|True|True|45|3061|
|完整v3修正预检|hunyuan-role-latest|100/100|True|True|True|99|126655|
|完整v3虚构预检|deepseek/deepseek-flash|100/100|True|True|True|105|142662|
|完整v3虚构预检|deepseek/deepseek-v4-flash-vision-exp|100/100|True|True|True|105|142663|
|完整v3虚构预检|deepseek-v4-flash-0731|0/0|False|False|False|1|0|
|完整v3虚构预检|glm-5.2|0/0|False|False|False|1|0|
|完整v3虚构预检|hunyuan-turbos-vision-video-20250728|100/100|True|True|True|105|144310|
|完整v3虚构预检|hy-role|100/100|True|True|True|105|135055|
|完整v3虚构预检|hy-vision-2.0-instruct|0/0|False|False|False|1|1396|
|完整v3虚构预检|kimi-k2.6|0/0|False|False|False|1|0|
|完整v3虚构预检|mimo-v2.6-pro|0/0|False|False|False|1|0|
|完整v3虚构预检|minimax-m3.1-flash|0/0|False|False|False|1|0|
|完整v3虚构预检|step-5-preview|0/0|False|False|False|1|2748|
|完整v3虚构预检|youtu-vita|17/55|True|False|False|60|85006|

完整v3预检的五次一致指label与temporal判定一致，不声称证据说明逐字节相同；100不同输入用于格式控制，虚构内容只有长期/临时两类模板，不作为语义准确率证据。腾讯Turbo虚构单项预检通过，真实多候选根结构持续失败；另用真实控制确认单条请求格式后，独立版本恢复，不把格式通过冒充人工质量通过。

返工：早期虚构生成器只改变未进入实际请求的字段，重复探测不能算100不同输入；已停用并独立重做。旧结果和未知中断用量保留：[{"purpose": "repeated fictional schema stability only, not 100 distinct samples qualification", "saved_responses": 96, "issued_request_files": 97, "unique_request_sha256_count": 1, "reported_tokens": 121536, "interrupted_request_usage_unknown": 1, "qualified": false, "cause": "generator varied a field absent from final wire payload; fixed in separate diverse run; old results preserved"}]。

缓存刷新返工：{"duplicate_current_other_side": {"completed_posts": 14, "known_tokens": 56291, "interrupted_unknown_requests": 2}, "new_deepseek_side_not_duplicate": {"completed_posts": 14, "known_tokens": 54192, "interrupted_unknown_requests": 2}, "raw_ledgers_unchanged": true, "regression_test": "tests/unit/test_temporal_response_replay.py"}。旧索引在同进程换侧后未刷新，造成另一完整侧重复调用；发现后中断，独立新入口每侧开始前刷新真实响应索引并重新严格校验。事故台账区分重复的混元侧和本就需要新标的DeepSeek侧；中断无响应的usage未知，不当作零。不改原始台账。

候选状态复核：当前目录仍标online的型号也可能实际402，不等于可调用。YT-VITA目录标discontinued，发现后中断其虚构预检，未进入标注池或裁判池；已发生调用与未知中断usage仍保留。没有以实际返回过200绕过退役状态或格式门槛。

后续预算仅条件估算：还需272个未审共同保留候选；按完成批次留存率预计2250候选、399对话、按每请求8候选双侧约564次POST，不含重试/换型。这是两侧都8条/请求的旧预算；若启用腾讯单条请求，以后面的新预算为准。换型或改调用分组后不承诺继承产率，不推断额度足够。

### 单条请求修复与新预算

真实分组探测：[{"size": 1, "transport_complete": true, "schema_valid": 1, "citation_valid": 1, "items": 1, "model": "hunyuan-turbos-vision-video-20250728", "prompt_sha256": "a52a79fd5c027f4cfc09d54de409f220ba88eec1a2bb45b0fa3c8c782dbeab6f", "quality_evidence": false, "candidate_modified": false, "validation_relaxed": false}, {"size": 2, "transport_complete": true, "schema_valid": 0, "citation_valid": 0, "items": 2, "model": "hunyuan-turbos-vision-video-20250728", "prompt_sha256": "a52a79fd5c027f4cfc09d54de409f220ba88eec1a2bb45b0fa3c8c782dbeab6f", "quality_evidence": false, "candidate_modified": false, "validation_relaxed": false}, {"size": 4, "transport_complete": true, "schema_valid": 0, "citation_valid": 0, "items": 4, "model": "hunyuan-turbos-vision-video-20250728", "prompt_sha256": "a52a79fd5c027f4cfc09d54de409f220ba88eec1a2bb45b0fa3c8c782dbeab6f", "quality_evidence": false, "candidate_modified": false, "validation_relaxed": false}]；分散真实输入控制：{"controls": [{"position": 0, "complete": true, "schema_valid": true, "citation_valid": true}, {"position": 100, "complete": true, "schema_valid": true, "citation_valid": true}, {"position": 200, "complete": true, "schema_valid": true, "citation_valid": true}, {"position": 400, "complete": true, "schema_valid": true, "citation_valid": true}, {"position": 550, "complete": true, "schema_valid": true, "citation_valid": true}], "all_format_and_quote_checks_passed": true, "human_quality_evidence": false, "prompt_unchanged": true, "validation_unchanged": true, "blind_pool_excluded_debug_items": 8}。仅验证格式/引用机械校验，不是语义质量证据。用于排查的真实条目保守排除出后续盲审及可采纳池；原多条请求不合格响应不修复、不混入。

当前分组预算：{"transport_packet_sizes": {"deepseek/deepseek-v4-flash-vision-exp": 8, "hunyuan-turbos-vision-video-20250728": 1}, "single_packet_complete_candidate_call_estimate": 5109, "single_packet_remaining_candidate_call_estimate": 2532, "single_packet_observed_token_means": {"deepseek/deepseek-v4-flash-vision-exp": {"observed_requests": 141, "observed_candidate_items": 1126, "reported_tokens": 530876, "mean_tokens_per_item": 471.47069271758437}, "hunyuan-turbos-vision-video-20250728": {"observed_requests": 373, "observed_candidate_items": 373, "reported_tokens": 777045, "mean_tokens_per_item": 2083.230563002681}}, "quota_sufficiency_not_inferred": true, "single_packet_remaining_tokens_conditional_estimate": 5748078}。token按真实单条调用小样本均值条件外推，完整来源长度不同会改变用量；调用数不含重试/换型，格式恢复不代表余额足够。运行状态以本报告increment字段为准。

API结构化输出虚构探测：{"at": "2026-10-22T07:54:06.277400+00:00", "model": "hunyuan-turbos-vision-video-20250728", "fictional_only": true, "quality_evidence": false, "prompt_sha256": "a52a79fd5c027f4cfc09d54de409f220ba88eec1a2bb45b0fa3c8c782dbeab6f", "schema_unmodified": true, "calls": 1, "http": 200, "usage": {"prompt_tokens": 1884, "completion_tokens": 1023, "total_tokens": 2907, "prompt_tokens_details": {"cached_tokens": 0}, "completion_tokens_details": {"reasoning_tokens": 0}}, "schema_valid": 0, "citation_valid": 0, "items": 8, "observed_disabled_thinking": true}。HTTP200不代表返回已满足原严格结构；失败包未进入任何标注池，不采用该方案；额外调用与token另记。

## 未完成项

- 旧池时效性筛选是否采用，等待负责人决定

- 补量被额度及真实批量格式故障阻塞；未达新增目标；本地阶段性盲审未发，补量完成后再交

- 当前可用裁判主备与人工校准仍有缺口

- 完整负样本会话数与负样本比例两个闸门尚未共同确认

- ECD只完成真实回填接入；系统误抽评测未运行
