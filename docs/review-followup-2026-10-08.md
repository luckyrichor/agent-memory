# 第二轮记忆评审修复

2026-10-08（北京时间）· Codex。基线 agent-memory@bb09ed0 + 本轮工作树；测试文件与源码 SHA256 见 [来源记录](measurements/review-followup-source-2026-10-08.json)。第一轮历史报告保留原验收版本；当前行为以本文为准。

## 核实与处理

| 问题 | 处理与验证 | 代价 / 边界 |
|---|---|---|
| 失效记忆可绕过恢复 | 修改前领域回归失败，确认允许 invalidated → archived；修改后领域和 HTTP/SDK 回归均阻止归档与恢复 | invalidated/superseded 只能转 deleted；不能重复改成相同失效状态 |
| 中文长查询全部片段 AND | 实际 PostgreSQL 旧 AND 查询为假、旧候选为空；中文改用分词后 OR，再按 ts_rank_cd 排序；相同 GIN 索引无需迁移 | 提高部分词重叠召回，同时可能引入噪声；无同义词时仍不能召回，不保证语义理解 |
| 正常敏感术语误拒 | 英文关键词加边界与凭据赋值语法；password 流程、secretary 服务等通过；赋值/令牌/归一化变体仍拒绝 | 正则不是完整 DLP；纯文字描述的凭据或复杂混淆仍可能漏检 |
| 异常向量立即死信 | INVALID_EMBEDDING（包括非 JSON 200、错维度、非有限/全零向量）允许最多两次指数退避重试，第三次失败 dead | 总任务 max_attempts 更小时仍提前到达上限；认证、缺失版本等永久错误保持不可重试 |
| 缓存命中排队 | 在 semaphore 前检查 TTL/LRU；入场后仍二次检查避免等候期间已填充的缓存重复调用 | 不新增跨进程缓存，也不承诺并发未命中的 single-flight |

## 生命周期契约

| 原状态 | 可到达状态 |
|---|---|
| active | archived / invalidated / superseded / deleted |
| archived | active / invalidated / superseded / deleted |
| invalidated / superseded | deleted |
| candidate / needs_review / rejected | deleted（候选批准走独立提取路径） |
| deleted | 无，终态 |

superseded 必须记录继任者；旧 archived 若已有 successor_id 仍禁止 restore。旧数据没有记录 archived 前状态，已发生的 invalidated → archived 无法仅凭现有行追溯；本次阻止后续绕过，没有宣称修复历史未知来源的归档。若部署环境已有此类数据，应结合业务审计确认并重新失效，不应直接批量猜测状态。

## 显式写入被拒时

HTTP 422 保留兼容的 `error.code=CONTENT_POLICY_REJECTED`，新增 `error.reason_code` 和固定提示。SDK `MemoryAPIError.reason_code` 同步可读；响应不回显命中的正文/凭据。

| reason_code | 调用方处理 |
|---|---|
| CONTENT_EMPTY / CONTENT_TOO_LONG | 填入非空内容 / 缩短内容 |
| CONTENT_SECRET_VALUE | 去除密码、密钥等赋值内容与 Bearer 凭据 |
| CONTENT_TOKEN_OR_CONTACT | 去除令牌、私钥、邮箱等明确模式 |
| CONTENT_NUMERIC_IDENTIFIER | 长数字编号脱敏后写入；不要把原始账号号段存入记忆正文 |

长数字仍采用保守拦截，无法仅靠外观可靠区分订单号和银行卡；本次没有增加任意长数字白名单。业务应只保存必要的结构化知识、避免原始编号与用户全文。完整 canonical UUID 的数字豁免保留，但不豁免全文的令牌检查。

## 验证与范围

- 四道门：208 pytest passed in 11.47s；ruff 通过；strict mypy 66 文件；foundation 8/8，零租户泄漏、零删除命中。
- [中文 v2 评测](measurements/followup-retrieval-zh.json)：保留旧 v1，新增 5 条非原文子串的改写，13 查询（12 正例、1 无关负例）、6 条人工构造记忆；正例 Recall@3/Hit@1=1.0，负例为空。只验证关键词片段重叠，不作为一般中文检索质量结论。
- 非 JSON 200/错维度第一次失败、第二次成功；持续异常第三次 dead；缓存用例先占满名额，命中仍立即返回。模型响应均使用 HTTP 夹具，无真实供应商调用。
- 本次无需新增扩展、索引迁移、软件安装；测试使用 PostgreSQL Testcontainers。未变更生产数据、启动常驻服务或替其他项目更新其固定依赖。
