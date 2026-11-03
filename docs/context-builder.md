# M6 Context Builder

POST /v1/memories/context 与 SDK MemoryClient.context。使用原 search 鉴权、RLS、workspace与active版本过滤，最多100个候选；offset固定为0。支持query/vector/model/type/workspace与token_budget(0..100000)。先按RRF得分 / memory_id排序，再去重，在Unicode边界裁剪最高分内容并尝试后续候选。返回精确版本引用、实际使用量、遗漏/裁剪计数。

默认计数器是utf8_bytes_conservative，按完整rendered字符串UTF-8字节计费，包含JSON元数据、安全包装与转义；不是某模型tokenizer的精确计数。给定预算不会溢出；小到无法装下任何内容时返回空字符串、0使用量。调用方需为系统prompt/工具/schema额外预留预算。应用层TokenCounter协议可替换计数器，必须确定且按前缀单调；API默认不宣称任意模型的精确窗口限制。

输出标明unverified_historical_reference/active_at_retrieval_snapshot，记忆作为数据JSON转义，不覆盖指令/权限。evidence_refs（E1，2026-11-03）：最多3条来源事件引用，只含event_id与role（origin→contradicts→verified_by→supports排序），多于3条时附evidence_total；为空表示没有记录来源事件（如显式写入），不是“未知”，也不代表已验证——trust标签不因有证据而改变；预算紧到连空内容条目都放不下时先丢引用（evidence_total仍保留）而不是丢记忆；不含事件正文、session名等，API的/search才返回完整引用。conflicts=not_assessed：冲突标注（E4）尚未做；状态为检索时快照，不能消除之后纠正/删除的竞争窗口。JSON包装不是单独充分的prompt-injection防御，调用方仍须使用数据边界。

M6验收覆盖预算0/不足/溢出、中文与转义、高价值优先、重复/稳定顺序、SDK API、workspace与跨租户隔离、删除退出上下文。首次全量发现SDK路由覆盖测试需同步新增入口，补调用后212测试通过；ruff、strict mypy67文件、foundation8/8均通过。来源为本轮基线+未提交修改，提交号见progress。
