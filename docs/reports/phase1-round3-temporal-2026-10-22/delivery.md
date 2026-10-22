# agent-memory 阶段1：长期记忆筛选与补量交接

生成时间：2026-10-22T05:54:55.085098+00:00；代码：8cad522852d50aae830aa5f2254be04f7a1bfc4f；存在已跟踪未提交改动：True。阶段1仍未验收，不进入阶段2。

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

原池时效性剔除 49；人工判错显式扣除 3，两类取并集，不重复扣。筛后拟采纳池 216。与此前人工正例合并的拟议规模 301。当前实际整池采纳仍为 0；等负责人看数据决定。

人工确认登记不由模型误剔除自动改写；模型筛选池与人工登记分别保存。没有自行设置筛选通过线。

## 增量批次

补量预算（条件估算，非实际产出）：以历史共同保留率和本轮时效性幸存率相乘约35.12%估算，需549个新共同保留候选（不依赖旧池待批采纳），预计1564个候选、278段对话、双模型约392次POST；更换模型/整百对话批次舍入会增加实际调用。抽样前可用对话1392段。

固定新种子；只用未用过且字段完整的BOTH/train，沿用原候选生成逻辑，原生标签字段不提供给模型。继承原会话切分。新增池在负责人独立72盲审前不计入可靠规模。

|批次|完整对话分母|候选|共同保留|时效性剔除（任一侧临时）|引用无效（任一侧）|
|---|---:|---:|---:|---:|---:|

补量未完成；未宣称达到700或1500。

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
    "Zhipu"
  ],
  "increment_models": [
    "deepseek-v4.1-flash-1017",
    "glm-5-2-260617"
  ],
  "old_pool_qualified_available_judges": [],
  "qualified_backup_count": 0,
  "required_backups": 1,
  "backup_gap": 1,
  "main_judge_missing": true,
  "note": "Ark GLM-5.2 becomes annotator/filter and cannot judge these data. Tencent HY4 remains vendor-independent for new DeepSeek+Zhipu increment but its current HTTP402 means unavailable. Other independent vendors require successful strict preflight and human calibration; no gate relaxed."
}

渠道不是厂商；不能沿用已经参与标注/过滤的GLM作为裁判。主裁判和备用仍有缺口，未放宽预检，人工校准也未完成。

## 用量与证据

完整门禁：pytest 419通过/18.0秒，ruff通过=True，strict mypy 96源文件，foundation零泄漏门通过=True。原始日志见validation.log。

当前台账POST尝试 231；成功响应报告token 1088580。失败响应无usage不按0实际用量推断。额外替代资格预检台账在tokenhub-pool-qualification目录，单独记录，未混为筛选调用。

腾讯替代候选资格检查额外调用 351 次（含普通429有限重试）。原结果 [{"model": "deepseek/deepseek-flash", "provider": "TokenHub", "calls": 105, "consistent_5": true, "format_n": 100, "format_valid": 100, "observed_disabled_thinking": true, "temperature_requested": 0, "api_json_mode": false, "reported_tokens": 7455, "passed": true}, {"model": "deepseek-v4-flash-202605", "provider": "TokenHub", "calls": 105, "consistent_5": true, "format_n": 100, "format_valid": 68, "observed_disabled_thinking": false, "temperature_requested": 0, "api_json_mode": false, "reported_tokens": 5183, "passed": false}, {"model": "hy-role", "provider": "TokenHub", "calls": 105, "consistent_5": true, "format_n": 100, "format_valid": 55, "observed_disabled_thinking": false, "temperature_requested": 0, "api_json_mode": false, "reported_tokens": 4084, "passed": false}, {"model": "hy3", "provider": "TokenHub", "calls": 1, "consistent_5": false, "format_n": 0, "format_valid": 0, "observed_disabled_thinking": false, "temperature_requested": 0, "api_json_mode": false, "reported_tokens": 0, "passed": false}, {"model": "hy4-preview", "provider": "TokenHub", "calls": 1, "consistent_5": false, "format_n": 0, "format_valid": 0, "observed_disabled_thinking": false, "temperature_requested": 0, "api_json_mode": false, "reported_tokens": 0, "passed": false}, {"model": "mimo-v2.6-flash", "provider": "TokenHub", "calls": 1, "consistent_5": false, "format_n": 0, "format_valid": 0, "observed_disabled_thinking": false, "temperature_requested": 0, "api_json_mode": false, "reported_tokens": 0, "passed": false}, {"model": "minimax-m3", "provider": "TokenHub", "calls": 1, "consistent_5": false, "format_n": 0, "format_valid": 0, "observed_disabled_thinking": false, "temperature_requested": 0, "api_json_mode": false, "reported_tokens": 0, "passed": false}]；限流补齐结果 [{"model": "deepseek-v4-flash-202605", "provider": "TokenHub", "qualified_at": "2026-10-22T05:53:45.338685+00:00", "consistent_5": true, "format_n": 100, "format_valid": 100, "observed_disabled_thinking": true, "new_post_attempts": 32, "cached_successes": 73, "new_reported_tokens": 2272, "original_failed_report_sha256": "f770d1926e297bd75d3bed2e0ae2fef51462032aef761a05dd8fb8c8e2642992", "temperature_requested": 0, "same_virtual_requests": true, "retry_rule": "only ordinary429, at most two retries/request; 3.1s minimum pacing plus30s after429; no quota/limit modification", "passed": true}]。旧报告不覆盖，Ark GLM历史预检复用不计本轮新调用。

原始CSV、来源、请求响应、映射、调用台账只在服务器.local/，公开仓库仅方法、哈希、指标。CSV SHA256：`5be99e4f6dcc8eb206fd672880efccb8ad96d45eef9f39a9b207016479e31397`。

重放汇总：`uv run python scripts/report-temporal-phase1.py`；真实筛选：`with-llm uv run python scripts/continue-temporal-screen.py`；补量：`with-llm uv run python scripts/run-temporal-increment.py`。运行过的完整结果使用缓存，不重复计费。

## 未完成项

- owner decision on old-pool temporal screening

- incremental annotation/export incomplete

- judge main/backup/calibration gaps

- full negative dialogue count/proportion confirmation

- ECD system false-extraction evaluation not run; intake only
