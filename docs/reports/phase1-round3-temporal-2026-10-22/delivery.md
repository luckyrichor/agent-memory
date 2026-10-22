# agent-memory 阶段1：长期记忆筛选与补量交接

生成时间：2026-10-22T06:52:11.980404+00:00；代码：6342c31fbef819b7a4575373400d723135cc404a；存在已跟踪未提交改动：True。阶段1仍未验收，不进入阶段2。

执行方案：`docs/plans/2026-10-22-agent-memory-interview-plan-v3.md`；SHA256 `06ad7319525c6b0f4eb7333c981b094dd1ed6ec41ae2e5ea1b46009306389418`。原作者保留，旧版未覆盖。按最新方案及负责人当前任务执行。

## 方案变化与口径

- PAL-Set optional after phase2, excluded from phase1 gold and recall

- long-term/short-term design: phase1 long-term only

- quota-based annotator replacement now automatic; whole affected side relabeled

- 内部旧口径：role-table says two backups but explicit judge selection says one; execute one

- 内部旧口径：role-table still lists old DeepSeek/MiMo; actual replacements explicitly authorized

- 内部旧口径：native22/old711 references remain historical; use verified owner returns/current registry

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

每100段固定对话为一个冻结批次；额度切换时当前批受影响一侧整批重标，已完成批保留独立模型来源，不拼接半批。此口径在首个增量批完成前确定，替代此前全部队列重启方式。格式无效条目严格拒绝并记程序uncertain，不删多余字段、不修改响应、不放宽引用校验；程序uncertain不作模型语义判断或一致率证据。时效性剔除为任一侧标临时的条目数，包含本已discard/uncertain项，与引用、结构无效计数可重叠，不应相加。

当前补量预算优先使用已完成批次的真实共同保留率；预筛池外推已退役，单侧估算仅保留为历史乐观口径。

固定新种子；只用未用过且字段完整的BOTH/train，沿用原候选生成逻辑，原生标签字段不提供给模型。继承原会话切分。新增池在负责人独立72盲审前不计入可靠规模。

|批次|完整对话分母|候选|共同保留|时效性剔除（任一侧临时）|引用无效（任一侧）|
|---|---:|---:|---:|---:|---:|
|0|100|585|77|79|54|
|1|100|567|78|95|81|

补量未完成；未宣称达到700或1500。

实际单侧进度（不是共同保留，不计可靠规模）：[{"batch": 0, "model": "deepseek-v4-flash-202605", "expected": 585, "completed": 585, "keep": 79, "temporary": 14, "citation_invalid": 6}, {"batch": 0, "model": "hunyuan-role-latest", "expected": 585, "completed": 585, "keep": 146, "temporary": 71, "citation_invalid": 54}, {"batch": 1, "model": "deepseek-v4-flash-202605", "expected": 567, "completed": 567, "keep": 98, "temporary": 18, "citation_invalid": 9}, {"batch": 1, "model": "hunyuan-role-latest", "expected": 567, "completed": 567, "keep": 125, "temporary": 82, "citation_invalid": 83}, {"batch": 2, "model": "deepseek-v4-flash-202605", "expected": 571, "completed": 176, "keep": 22, "temporary": 3, "citation_invalid": 1}, {"batch": 2, "model": "hunyuan-role-latest", "expected": 571, "completed": 176, "keep": 37, "temporary": 23, "citation_invalid": 30}]

预算更正：早期按预筛701池外推原始候选不合适，已退役该估计。当前完整单侧保留79/585；如果另一侧不再损失任何候选，条件乐观外推需4066候选、721对话、约1018次双侧POST。该单侧口径不能当作实际共同保留率或产出承诺；不设新产量质量门。

按已完成批次条件外推：155/1152共同保留，若后续同分布，预计4081候选、723对话、双侧1022次POST产生目标549条；未含重试/换型重标/百会话舍入，不是实际可靠规模。

## ECD负样本小金标准

标注方式：**AI 草稿加人工确认**，不是人工独立标注；Agent未改任何人工标签。全表120段：无应记内容108段（90.00%，分母120）；有应记内容7段；不确定5段单列，不计正负。

冻结非人工字段逐项核对一致，旧120表未覆盖。108段作为已确认负样本小金标准；7段正会话不自动折算为7个DuLeMon记忆点。不代表ECD总体分布，尚未用系统运行误抽评测。原文、审核理由与应记内容仅服务器.local/，对外只方法、哈希、指标。

回填SHA256：`95c81861d698d93e453d8c511da12e3470c2608c4368fc5823708f6b7fad5d15`。

## 裁判池影响

{
  "old_pool_including_screening_annotation_vendors": [
    "DeepSeek",
    "Tencent",
    "Zhipu"
  ],
  "answer_vendor": "ByteDance",
  "old_pool_excluded_judge_vendors": [
    "ByteDance",
    "DeepSeek",
    "Tencent",
    "Zhipu"
  ],
  "increment_annotation_vendors": [
    "DeepSeek",
    "hunyuan-role-latest"
  ],
  "increment_models": [
    "deepseek-v4-flash-202605",
    "hunyuan-role-latest"
  ],
  "increment_vendor_independent_historically_preflighted_judge_vendors": [
    "Zhipu"
  ],
  "increment_currently_available_qualified_judge_vendors": [],
  "latest_availability_issue": "Ark GLM SetLimitExceeded during actual increment; Tencent GLM historical402; no new judge calls made",
  "old_pool_qualified_available_judges": [],
  "qualified_backup_count": 0,
  "required_backups": 1,
  "backup_gap": 1,
  "main_judge_missing": true,
  "note": "Ark GLM-5.2 becomes annotator/filter and cannot judge these data. Tencent HY4 remains vendor-independent for new DeepSeek+Zhipu increment but its current HTTP402 means unavailable. Other independent vendors require successful strict preflight and human calibration; no gate relaxed."
}

旧池时效性筛选实际用过GLM，因此旧池不能由智谱裁判；新补量若最终仅用DeepSeek/腾讯，智谱在厂商独立性上可用，历史预检也通过，但Ark本轮已SetLimitExceeded，不能称当前可用。原GLM部分补量结果已退役，不混入新批。当前稳定可用主裁判缺失，备用仍缺至少一个；未放宽预检，人工校准也未完成。

## 用量与证据

完整门禁：pytest 427通过/17.8秒，ruff通过=True，strict mypy 98源文件，foundation零泄漏门通过=True。原始日志见validation.log。

当前台账POST尝试 611；成功响应报告token 2526496。失败响应无usage不按0实际用量推断。额外替代资格预检台账在tokenhub-pool-qualification目录，单独记录，未混为筛选调用。

腾讯替代候选资格检查额外调用 596 次（含普通429有限重试）。原结果 [{"model": "deepseek/deepseek-flash", "provider": "TokenHub", "calls": 105, "consistent_5": true, "format_n": 100, "format_valid": 100, "observed_disabled_thinking": true, "temperature_requested": 0, "api_json_mode": false, "reported_tokens": 7455, "passed": true}, {"model": "deepseek-v4-flash-202605", "provider": "TokenHub", "calls": 105, "consistent_5": true, "format_n": 100, "format_valid": 68, "observed_disabled_thinking": false, "temperature_requested": 0, "api_json_mode": false, "reported_tokens": 5183, "passed": false}, {"model": "hy-role", "provider": "TokenHub", "calls": 105, "consistent_5": true, "format_n": 100, "format_valid": 55, "observed_disabled_thinking": false, "temperature_requested": 0, "api_json_mode": false, "reported_tokens": 4084, "passed": false}, {"model": "hy3", "provider": "TokenHub", "calls": 1, "consistent_5": false, "format_n": 0, "format_valid": 0, "observed_disabled_thinking": false, "temperature_requested": 0, "api_json_mode": false, "reported_tokens": 0, "passed": false}, {"model": "hy4-preview", "provider": "TokenHub", "calls": 1, "consistent_5": false, "format_n": 0, "format_valid": 0, "observed_disabled_thinking": false, "temperature_requested": 0, "api_json_mode": false, "reported_tokens": 0, "passed": false}, {"model": "mimo-v2.6-flash", "provider": "TokenHub", "calls": 1, "consistent_5": false, "format_n": 0, "format_valid": 0, "observed_disabled_thinking": false, "temperature_requested": 0, "api_json_mode": false, "reported_tokens": 0, "passed": false}, {"model": "minimax-m2.7", "provider": "TokenHub", "calls": 1, "consistent_5": false, "format_n": 0, "format_valid": 0, "observed_disabled_thinking": false, "temperature_requested": 0, "api_json_mode": false, "reported_tokens": 217, "passed": false}, {"model": "minimax-m3", "provider": "TokenHub", "calls": 1, "consistent_5": false, "format_n": 0, "format_valid": 0, "observed_disabled_thinking": false, "temperature_requested": 0, "api_json_mode": false, "reported_tokens": 0, "passed": false}]；限流补齐结果 [{"model": "deepseek-v4-flash-202605", "provider": "TokenHub", "qualified_at": "2026-10-22T05:53:45.338685+00:00", "consistent_5": true, "format_n": 100, "format_valid": 100, "observed_disabled_thinking": true, "new_post_attempts": 32, "cached_successes": 73, "new_reported_tokens": 2272, "original_failed_report_sha256": "f770d1926e297bd75d3bed2e0ae2fef51462032aef761a05dd8fb8c8e2642992", "temperature_requested": 0, "same_virtual_requests": true, "retry_rule": "only ordinary429, at most two retries/request; 3.1s minimum pacing plus30s after429; no quota/limit modification", "passed": true}, {"model": "hy-role", "provider": "TokenHub", "qualified_at": "2026-10-22T05:56:02.931023+00:00", "consistent_5": true, "format_n": 100, "format_valid": 100, "observed_disabled_thinking": true, "new_post_attempts": 45, "cached_successes": 60, "new_reported_tokens": 3061, "original_failed_report_sha256": "7de42bd12d0223dba800fcb4f419bed75fe6bd625cbca1bd91e1135477aad882", "temperature_requested": 0, "same_virtual_requests": true, "retry_rule": "only ordinary429, at most two retries/request; 3.1s minimum pacing plus30s after429; no quota/limit modification", "passed": true}]。旧报告不覆盖，Ark GLM历史预检复用不计本轮新调用。

原始CSV、来源、请求响应、映射、调用台账只在服务器.local/，公开仓库仅方法、哈希、指标。CSV SHA256：`5be99e4f6dcc8eb206fd672880efccb8ad96d45eef9f39a9b207016479e31397`。

重放汇总：`uv run python scripts/report-temporal-phase1.py`；真实筛选：`with-llm uv run python scripts/continue-temporal-screen.py`；补量：`with-llm uv run python scripts/run-temporal-increment.py`。运行过的完整结果使用缓存，不重复计费。

完整v3格式资格检查：[{"model": "hunyuan-role-latest", "provider": "TokenHub", "qualified_at": "2026-10-22T06:18:31.275251+00:00", "consistent_5": true, "format_n": 100, "format_valid": 100, "distinct_inputs": 100, "observed_disabled_thinking": true, "citation_valid": 100, "new_post_attempts": 99, "new_reported_tokens": 126655, "prompt_sha256": "a52a79fd5c027f4cfc09d54de409f220ba88eec1a2bb45b0fa3c8c782dbeab6f", "prior_repeated_control_summary_sha256": "a1e46a1dd15190e2c5b6c42fecd409943f6b17e95c010aa6c35b1e83b766c9cf", "temperature_requested": 0, "fictional_only": true, "schema": "full v3 evidence plus temporal", "passed": true}, {"model": "hy-vision-2.0-instruct", "provider": "TokenHub", "qualified_at": "2026-10-22T06:27:17.615657+00:00", "fictional_only": true, "schema": "full v3 plus temporal", "consistent_5": false, "format_n": 0, "format_valid": 0, "distinct_inputs": 0, "observed_disabled_thinking": false, "calls": 1, "reported_tokens": 1396, "prompt_sha256": "a52a79fd5c027f4cfc09d54de409f220ba88eec1a2bb45b0fa3c8c782dbeab6f", "temperature_requested": 0, "passed": false}, {"model": "mimo-v2.6-pro", "provider": "TokenHub", "qualified_at": "2026-10-22T06:28:46.920462+00:00", "fictional_only": true, "schema": "full v3 plus temporal", "consistent_5": false, "format_n": 0, "format_valid": 0, "distinct_inputs": 0, "observed_disabled_thinking": false, "calls": 1, "reported_tokens": 0, "prompt_sha256": "a52a79fd5c027f4cfc09d54de409f220ba88eec1a2bb45b0fa3c8c782dbeab6f", "temperature_requested": 0, "passed": false}, {"model": "step-5-preview", "provider": "TokenHub", "qualified_at": "2026-10-22T06:29:12.652660+00:00", "fictional_only": true, "schema": "full v3 plus temporal", "consistent_5": false, "format_n": 0, "format_valid": 0, "distinct_inputs": 0, "observed_disabled_thinking": false, "calls": 1, "reported_tokens": 2748, "prompt_sha256": "a52a79fd5c027f4cfc09d54de409f220ba88eec1a2bb45b0fa3c8c782dbeab6f", "temperature_requested": 0, "passed": false}]。返工：早期虚构生成器只改变未进入最终请求的字段，实际为同一输入的重复稳定性探测，不能作为100种输入预检；已停用并独立重做，旧记录与未知中断用量保留：[{"purpose": "repeated fictional schema stability only, not 100 distinct samples qualification", "saved_responses": 96, "issued_request_files": 97, "unique_request_sha256_count": 1, "reported_tokens": 121536, "interrupted_request_usage_unknown": 1, "qualified": false, "cause": "generator varied a field absent from final wire payload; fixed in separate diverse run; old results preserved"}]。

## 未完成项

- owner decision on old-pool temporal screening

- incremental annotation/export incomplete

- judge main/backup/calibration gaps

- full negative dialogue count/proportion confirmation

- ECD system false-extraction evaluation not run; intake only
