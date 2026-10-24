> 🤖 由 Codex 生成 · 2026-10-24 · 来源 agent-memory@593c936 · 工具 lark-cli profile codex

# agent-memory 阶段 2 B0 暂停交接报告

生成时间：2026-10-24T12:33:16.612555+08:00。本报告分析提交 `593c936`；B0业务源码 `1e9d6f3`；本轮实际测量工具提交 `e36e4ce`。生成前工作区状态：?? docs/reports/phase2-b0-pause-2026-10-24/。本次仅新增报告，不改指标、切分、标签、运行配置，不重启计算。

## 一、当前结论

- 当前托管任务状态：**inactive，已暂停，阶段 2 未完成/未验收，未进入阶段 3**。
- 已完成答题与判分 **360 条实验行**；实验行含系统组、模式与重复，不是独立问题数或会话数。均为未校准诊断，不能作为正式 B0 成绩。
- 已准备上下文结果 **960 行**，不等于已完成判分；完整人工校准表尚未生成，公网压测尚未开展。
- 向量403/AccountOverdueError识别遗漏已修复并通过发布检查。替代预检检查了 23 个型号/Key组合，按当前实现门槛合格 0 个。

**重要纠正：**原向量模型在另一 Key 上实际调用成功。当前“暂无替代通过预检”的原因包含我额外设置的向量精确一致性门槛，不能概括为所有额度都不足，也不能称该门槛是方案冻结要求。

## 二、数据与完成范围

仅使用冻结开发集；测试集未执行。以下为完成答题判分的实验行：

| 数据集 | 完成实验行 | 方法与对照 | 口径等级 |
|---|---:|---|---|
| locomo | 240 | 直写/全链路、四系统组、三次原始重复；无记忆/全文/朴素向量/SUT | 外部公开基准；裁判未校准诊断 |
| longmemeval_oracle | 120 | 直写/全链路、四系统组、三次原始重复；无记忆/全文/朴素向量/SUT | 外部公开基准；裁判未校准诊断 |

LongMemEval S、PerLTQA、真实中文查询、DuLeMon金标准与ECD负样本的本轮完整功能测量仍未完成，不填造结果。阶段1全局数据口径保持原样：真实中文金标准、混合来源会话与ECD负样本不冒充本次开发集样本量。ECD为客服领域，不能代表一般对话；原文仅保留服务器私有目录。构造题仅流程验证，不混入真实中文总分。

## 三、实际模型与可比性

| 角色/实际型号 | 已判分实验行 |
|---|---:|
| 答题/hy4-preview | 162 |
| 答题/hunyuan-role-latest | 84 |
| 答题/hy-mt2-plus | 114 |
| 裁判/glm-5.2 | 360 |

同系列换型续跑按负责人授权记录，不能把这张混用版本的表称为单一精确型号实验。`hy-mt2-plus` 对通用问答角色的适用性未专项核实；通用格式预检不证明与原模型效果等价。因两模式或重复轮次可能使用不同型号，差距不能单独归因于记忆系统。主裁判未完成负责人校准，不发布正式质量结论。

## 四、暂停原因与方案出入

1. 原向量调用返回403/AccountOverdueError。此前代码只识别部分额度错误，未把该错误交给自动切换逻辑，而以INVALID_EMBEDDING_RESPONSE结束；原失败记录保留。此缺陷已修复，普通AccessDenied不误当额度错误。
2. 最新方案第7节“同一输入连跑五次，判分结果一致”针对裁判判分。执行脚本却对向量施加“五次浮点数组序列化哈希完全相同”的额外硬门槛。**这是执行偏差，应修正此前“没有放宽任何冻结校验”的不准确表述。**
3. 原向量模型在另一Key上的实测：
   - HTTP成功 106 次；格式检查 100/100。
   - 五次比较向量出现 3 个不同哈希；最大坐标绝对差 0.0107421875，相对第一条的最小余弦相似度 0.99554126222。
   - 这些差异大小仅作诊断，不据此新设验收线，也不将“同型号换Key”直接当成向量空间已验证等价。
4. 原方案整组换型规则已被负责人同系列续跑授权覆盖；不同系列仍整组重跑，向量空间变化仍重建。指标定义、数据切分与正式验收线未改变。

## 五、向量替代预检记录

以下仅给型号、厂商接口、失败类别，不含密钥、账号或令牌。组合计数包含同型号不同Key；不把目录可读当成模型可用。

| 型号 | 接口 | 调用尝试 | HTTP分布 | 当前实现通过 |
|---|---|---:|---|---|
| doubao-embedding-vision-251215 | Ark | 106 | {"200": 106} | False |
| doubao-embedding-large-text-240915 | Ark | 1 | {"404": 1} | False |
| doubao-embedding-large-text-240915 | Ark | 1 | {"404": 1} | False |
| doubao-embedding-large-text-250515 | Ark | 1 | {"404": 1} | False |
| doubao-embedding-large-text-250515 | Ark | 1 | {"404": 1} | False |
| doubao-embedding-text-240515 | Ark | 1 | {"404": 1} | False |
| doubao-embedding-text-240515 | Ark | 1 | {"404": 1} | False |
| doubao-embedding-text-240715 | Ark | 1 | {"404": 1} | False |
| doubao-embedding-text-240715 | Ark | 1 | {"404": 1} | False |
| doubao-embedding-vision-241215 | Ark | 1 | {"404": 1} | False |
| doubao-embedding-vision-241215 | Ark | 1 | {"404": 1} | False |
| doubao-embedding-vision-250328 | Ark | 1 | {"404": 1} | False |
| doubao-embedding-vision-250328 | Ark | 1 | {"404": 1} | False |
| doubao-embedding-vision-250615 | Ark | 1 | {"404": 1} | False |
| doubao-embedding-vision-250615 | Ark | 1 | {"404": 1} | False |
| kinfra-text-embedding-0.6b | TokenHub | 1 | {"400": 1} | False |
| kinfra-text-embedding-0.6b | TokenHub | 1 | {"400": 1} | False |
| kinfra-text-embedding-4b | TokenHub | 1 | {"400": 1} | False |
| kinfra-text-embedding-4b | TokenHub | 1 | {"400": 1} | False |
| kinfra-vl-embedding-2b | TokenHub | 1 | {"400": 1} | False |
| kinfra-vl-embedding-2b | TokenHub | 1 | {"400": 1} | False |
| kinfra-vl-embedding-8b | TokenHub | 1 | {"400": 1} | False |
| kinfra-vl-embedding-8b | TokenHub | 1 | {"400": 1} | False |

## 六、指标与对比：校准前诊断

每行均给数据集/规模/方法/对照。方法为冻结开发抽样、会话聚类bootstrap；对照包含无记忆、全文塞入、朴素向量与系统。下列E1仅供排查，不能宣称正式准确率，也不证明已覆盖完整指标目录。完整已有诊断观察见numbers.json，未测指标不填零。

| 数据集/模式/系统 | 指标 | 值 | 分母 | 会话数 | 95%区间 |
|---|---|---:|---:|---:|---|
| longmemeval_oracle/direct/no-memory | E1（裁判未校准） | 0.2 | 15.0 | 5 | [0.0, 0.6] |
| longmemeval_oracle/direct/full-context | E1（裁判未校准） | 0.8 | 15.0 | 5 | [0.4, 1.0] |
| longmemeval_oracle/direct/naive-vector | E1（裁判未校准） | 1.0 | 15.0 | 5 | [1.0, 1.0] |
| longmemeval_oracle/direct/system | E1（裁判未校准） | 0.7333333333333333 | 15.0 | 5 | [0.5333333333333333, 0.9333333333333333] |
| longmemeval_oracle/full/no-memory | E1（裁判未校准） | 0.2 | 15.0 | 5 | [0.0, 0.6] |
| longmemeval_oracle/full/full-context | E1（裁判未校准） | 0.8 | 15.0 | 5 | [0.4, 1.0] |
| longmemeval_oracle/full/naive-vector | E1（裁判未校准） | 0.13333333333333333 | 15.0 | 5 | [0.0, 0.4] |
| longmemeval_oracle/full/system | E1（裁判未校准） | 0.2 | 15.0 | 5 | [0.0, 0.6] |
| locomo/direct/no-memory | E1（裁判未校准） | 0.0 | 16.0 | 1 | [0.0, 0.0] |
| locomo/direct/full-context | E1（裁判未校准） | 0.4117647058823529 | 17.0 | 1 | [0.4117647058823529, 0.4117647058823529] |
| locomo/direct/naive-vector | E1（裁判未校准） | 0.1875 | 16.0 | 1 | [0.1875, 0.1875] |
| locomo/direct/system | E1（裁判未校准） | 0.23529411764705882 | 17.0 | 1 | [0.23529411764705882, 0.23529411764705882] |
| locomo/full/no-memory | E1（裁判未校准） | 0.0 | 26.0 | 1 | [0.0, 0.0] |
| locomo/full/full-context | E1（裁判未校准） | 0.08 | 25.0 | 1 | [0.08, 0.08] |
| locomo/full/naive-vector | E1（裁判未校准） | 0.0 | 25.0 | 1 | [0.0, 0.0] |
| locomo/full/system | E1（裁判未校准） | 0.0 | 26.0 | 1 | [0.0, 0.0] |

区间按原聚合器的会话聚类bootstrap输出；重复轮次波动、分题型最差项、无效结果及全指标覆盖状态保留在numbers.json。最差题型仅为未校准局部抽样诊断，不能把局部数据当全指标验收。

## 七、失败案例（仅不透明ID，原文私有）

| 案例ID | 数据集 | 模式/系统 | 原因分类（待人工校准） |
|---|---|---|---|
| f8fc8f78850fa4911309d5e401c45dea0acf8afe6788c7cfa9334e21fdee009e | longmemeval_oracle | direct/no-memory | no_history_baseline_mismatch |
| aa5da7f33d536b98142e67d0492480247f5fe686c22b62174a192a90e41de9b7 | longmemeval_oracle | direct/no-memory | no_history_baseline_mismatch |
| 11ac5aa30054efdfa6e989fe20326fa44cc190fe935f6929e1127b6c027dbab8 | longmemeval_oracle | direct/system | answer_mismatch_despite_context_pending_human_calibration |
| fadf5c71d5ad711c890cfdb471e9af1ae0750687676fbf561f73f84ec7a62a3a | longmemeval_oracle | direct/no-memory | no_history_baseline_mismatch |
| 09f040288c87069de53d8711a3dee4b71cd35dc916e7b16d15ada7bfc838332e | longmemeval_oracle | direct/full-context | answer_mismatch_despite_context_pending_human_calibration |
| 28ca53f5815efa87c54190739c3a7706f611e77c934ee33c1b53081da23e31a8 | longmemeval_oracle | direct/no-memory | no_history_baseline_mismatch |
| 55c182ff7cd1eefff3a87bb1f35ea408aa7b9320941ea9b5e44bc557325806b3 | longmemeval_oracle | direct/system | answer_mismatch_despite_context_pending_human_calibration |
| 8c4ad1854e3efb0bc3845977d14fe0507ecb4679842f36317ac90faeff777425 | longmemeval_oracle | direct/no-memory | no_history_baseline_mismatch |
| 5991acacc7cfa126a3d49c10f61eb3d6b11817fc4caa1f21e14829b00a3b7fc0 | longmemeval_oracle | direct/no-memory | no_history_baseline_mismatch |
| 770300781fb969f27e9960c7cec87fa04f30beaabc9b2aa1bf3e28d4e59a2158 | longmemeval_oracle | direct/no-memory | no_history_baseline_mismatch |
| 67226902bb1db1b08452d1c437459a71a0d2892be7620959447e055da699e4b7 | longmemeval_oracle | direct/full-context | answer_mismatch_despite_context_pending_human_calibration |
| f87509a857496d9c087b31ffbf395968e0ed0f2565fb1208e5f389b6d5927863 | longmemeval_oracle | direct/no-memory | no_history_baseline_mismatch |
| df0ae0d18d27f1d9ffec300be1cbf91e75117dbb242c61bcb5b73b35052e52f2 | longmemeval_oracle | direct/no-memory | no_history_baseline_mismatch |
| eb823902958d3d39f86e02312df24a9e9eed11328c86ed6745427f79d0a51775 | longmemeval_oracle | direct/no-memory | no_history_baseline_mismatch |
| f9223e6878acbc185712f2233d2201251bc6d7d0eff205ac19eebbf85022ea40 | longmemeval_oracle | direct/system | answer_mismatch_despite_context_pending_human_calibration |
| c37a6e24ee3a3ac6e963da4d8f0d3a362020e7fd569a9d3f263b7a0aafeadb01 | longmemeval_oracle | direct/no-memory | no_history_baseline_mismatch |
| a3ae6c2720b26bc50b58bf29cfd0a93639081694b7c47d3f9e6295535c1b4936 | longmemeval_oracle | direct/full-context | answer_mismatch_despite_context_pending_human_calibration |
| b26c516740b6730761ba67695f4fe39da797136c6abfe7c0cccc5dc87de9663a | longmemeval_oracle | direct/system | answer_mismatch_despite_context_pending_human_calibration |
| d36a594084d8eb4f830088e67bba7cbc2435cc737ef7977a0784f84b42bf3c61 | longmemeval_oracle | direct/no-memory | no_history_baseline_mismatch |
| a1f939e860d0c2c6e8136f07d755085dcaa6626d778012a020dfe430f1f0da93 | longmemeval_oracle | full/no-memory | no_history_baseline_mismatch |

以上为已有模型诊断失败，负责人尚未复核；不能称人工确认错误。

## 八、资源与验证证据

最后一次尝试的最终usage台账：记录 2264 条，新HTTP尝试 1638 次，向量重放 626 条。仅统计最后一次尝试，不是所有历史轮次总成本；继承的答题行对应调用仍在父台账。结束status快照与最终台账计数可能因并发收尾不同，以最终usage台账为准，不混加。

| 角色 | 新HTTP尝试 | 接口已报告总token | usage缺失条数 |
|---|---:|---:|---:|
| embedding | 1050 | 16218 | 668 |
| extraction | 588 | 156780 | 7 |

修复提交fdd8944的发布检查：pytest 454 passed，44.39秒；ruff、strict mypy与foundation通过。这是评测工具回归，不代表真实模型测量或性能压测已验收。日志SHA256：`6be11d6b092848d4002bdf74c54e79f933c5804384a69977183551095bb31fc7`。

## 九、未完成项、局限与恢复条件

- 完成本轮其余开发集、两模式与关键结论重复；补齐功能指标观察适配器，缺项如实列出。
- 先纠正向量精确一致性门槛的适用范围，按方案核对同版本向量兼容性；本次报告未改动该预检实现，未用这个诊断代替正式检索质量验证。
- 保留已有完成检查点；若确实更换向量模型/空间，则全量重建相关索引，不混向量。
- 全部所选功能测量完成后才导出人工栏空白、隐藏裁判结果的私有校准表，交负责人并暂停；当前没有表需要负责人填写。
- 主备裁判人工校准、重复判分稳定性与正式质量验收尚未完成。
- 独立跨地域压测机尚待准备，PF测量未开展；访问材料须私有交付，不在聊天或报告中出现密钥。
- 当前仅小规模固定开发抽样，不代表全量基准、测试集、真实用户或生产环境效果；三次重复的波动也可能包含模型版本混用因素。
- 需要负责人参与的是后续人工校准和压测机交付；不请求降低指标、改变测试集隔离或用充值代替预检。

## 十、复核材料

本报告所有数字由生成脚本从冻结文件、最终调用台账和既有诊断聚合计算；numbers.json保留证据哈希。附件包不包含原始对话、逐题答案、数据库快照、凭据或授权令牌。
