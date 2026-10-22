
## 时效性补量：严格输出拒绝与固定批冻结（Codex，北京时间2026-10-22，进行中）

旧入口将模型单项结构错误升级为整批异常；两种混元角色型号实际有时在引用对象加入禁止字段。保留失败响应，未删字段补救。新增严格输出适配器：单项不满足原严格结构或精确引用校验就记程序uncertain，不成为keep或discard；其他合格项继续，根结构或ID覆盖错误则整次响应全部拒绝。原始响应不修改，程序uncertain不得充模型语义判断或一致率证据。已成功真实响应按请求哈希重放并重新严格校验，缓存不算新增API调用与用量。

每百段固定对话独立冻结；切换时当前批受影响侧完整重标，完成批保持独立模型、提示词、校验器来源。此范围在首批完成前确定，替代此前全部选中队列重启，未拼接半批模型。模型输出错误与普通限流、额度上限分别留账；未改安全用量上限或计费。

预检返工：早期虚构生成器变动字段没有进入实际请求，重复响应仅能作为结构稳定性观察，不能作多样本资格证据。发现后停止，另生成真实不同请求，通过完整格式及关闭思考预检；原失败/中断记录、未知用量保留。后续备选仍用同一门槛，不以一个成功响应冒充合格。

报告生成器已适配批次注册表和进行中状态，修复无最终审核表时的KeyError；原python命令不存在导致首次修改未执行，改用python3后重放通过。调用台账按物理请求身份去重；真实缓存不重复计费。旧池拟采纳并集按集合核算，人工确认项不由模型筛选误伤自动改写。之前预筛池留存率不代表原始新增候选产率，已退役该预算，改用完成批次的条件共同保留率，不作为产出承诺。

截至本条记录完成批次摘要（脚本读取注册表）：

[{"batch": 0, "conversations": 100, "candidates": 585, "joint_keep": 77, "temporal_removed": 79, "citation_invalid": 54, "schema_invalid": 1}, {"batch": 1, "conversations": 100, "candidates": 567, "joint_keep": 78, "temporal_removed": 95, "citation_invalid": 81, "schema_invalid": 7}]

新增可靠采纳仍为零，独立盲审未交付。补量与备选检查进行中；四门最近完整日志check-final.log，精确测试数量、时间与文件数由交接脚本读取。阶段1未验收。

### 自动切换缓存缺陷与修复（同轮，未掩盖额外用量）

自动换DeepSeek侧后，缓存索引只在进程启动时建立，未看见该进程后来已完成的混元侧，导致重复请求。发现后中断旧入口，原始响应和台账不改；新独立入口每侧启动前刷新真实响应索引、重新执行原严格校验。完成批独立冻结，当前完整混元侧缓存复用，当前DeepSeek新标仍继续。回归测试使用完全虚构请求：先建立索引，再加入后完成侧，确认后续side必须缓存命中且不发API。完整四门再次通过，精确数量和时间读取check-final.log。

事故台账（脚本读取）：

{"duplicate_current_other_side": {"completed_posts": 14, "known_tokens": 56291, "interrupted_unknown_requests": 2}, "new_deepseek_side_not_duplicate": {"completed_posts": 14, "known_tokens": 54192, "interrupted_unknown_requests": 2}, "raw_ledgers_unchanged": true, "regression_test": "tests/unit/test_temporal_response_replay.py"}

已完成的重复调用明确计入用量；中断时无响应usage未知，不按零推断。不是格式/引用标准的放宽。新备选预检仍在进行，不把未完成预检列为合格。阶段1仍未验收，新增候选未采纳。

### 额度与调用分组故障分开；单条请求恢复（最新进行中）

负责人询问是否所有模型额度耗尽，已明确回复：不是。部分型号真实402，另有仍可调用的腾讯型号却持续返回不合规多候选根结构；不能从局部调用失败推断所有余额。旧失败尝试已关闭并冻结完整批快照，未把失败侧纳入金标，也未发阶段性盲审包。

继续定位发现相同模型/提示词/候选/严格校验下，单条请求可用，多条请求不合规。真实分组探测与分散真实输入控制均独立保留；这不是语义质量验证，不使用人工标签调提示词。用于排查的真实ID保守排除后续盲审与可采纳池。新的V5入口只改腾讯请求分组；当前受影响侧整批重标，旧无效响应不修复、不混入，另一完整侧真实响应缓存重验复用。先前“无可用批量组合”的结论仅属于旧多候选调用方式，不能据此说所有模型或所有额度不可用。

脚本读取控制结果：

{"packet_probe": [{"size": 1, "transport_complete": true, "schema_valid": 1, "citation_valid": 1, "items": 1, "model": "hunyuan-turbos-vision-video-20250728", "prompt_sha256": "a52a79fd5c027f4cfc09d54de409f220ba88eec1a2bb45b0fa3c8c782dbeab6f", "quality_evidence": false, "candidate_modified": false, "validation_relaxed": false}, {"size": 2, "transport_complete": true, "schema_valid": 0, "citation_valid": 0, "items": 2, "model": "hunyuan-turbos-vision-video-20250728", "prompt_sha256": "a52a79fd5c027f4cfc09d54de409f220ba88eec1a2bb45b0fa3c8c782dbeab6f", "quality_evidence": false, "candidate_modified": false, "validation_relaxed": false}, {"size": 4, "transport_complete": true, "schema_valid": 0, "citation_valid": 0, "items": 4, "model": "hunyuan-turbos-vision-video-20250728", "prompt_sha256": "a52a79fd5c027f4cfc09d54de409f220ba88eec1a2bb45b0fa3c8c782dbeab6f", "quality_evidence": false, "candidate_modified": false, "validation_relaxed": false}], "single_packet_controls": {"controls": [{"position": 0, "complete": true, "schema_valid": true, "citation_valid": true}, {"position": 100, "complete": true, "schema_valid": true, "citation_valid": true}, {"position": 200, "complete": true, "schema_valid": true, "citation_valid": true}, {"position": 400, "complete": true, "schema_valid": true, "citation_valid": true}, {"position": 550, "complete": true, "schema_valid": true, "citation_valid": true}], "all_format_and_quote_checks_passed": true, "human_quality_evidence": false, "prompt_unchanged": true, "validation_unchanged": true, "blind_pool_excluded_debug_items": 8}}

接口JSON Schema参数另做一次完全虚构探测，实际返回仍不满足原严格结构，未采用。新增单条调用预算与token按真实响应均值重算，不能沿用双侧每请求八条的旧预算；不推断剩余额度足够。补量继续，当前人工规模不变、新增未采纳、阶段1未验收。完整四门日志check-final.log。
