# 阶段 1 第三轮后续交接

🤖 由 Codex 生成 · 2026-10-21（北京时间）· 来源 agent-memory@6dd38091f709 · 本地 CLI；未提交源码修改：False。原方案署名保留，不改为助手原创。

**阶段 1 仍未验收，未进入阶段 2。** 本报告接续[上次收尾报告](../phase1-round3-closeout-2026-10-21/delivery.md)；旧报告保留为历史。以下数字均由 `scripts/report-phase1-followup.py` 从实测记录、数据清单和验证日志生成，完整字段见 [report.json](report.json)。

## 最新方案与旧版差异

已完整读取并原样归档 [最新版方案](../../plans/2026-10-21-agent-memory-interview-plan.md)。新原件 SHA256：`a199f472d908a603df158e2452ce8b58ef36210e8ff9a308273327e41b5d299d`。与旧仓库原件共有 7 处差异块，见[逐行差异](plan-diff.patch)。

- 运行时与答题改用新版豆包；公开中文标注改为 DeepSeek + MiMo。
- ECD 改为暂定负样本与负责人小样人工金标准，取消其模型 κ 闸门；原生标注人工一致率不足阈值时仅使用人工确认子集。
- 裁判可来自腾讯与 Ark，按该表的答题/标注厂商排除；预检与实际调用成功后选择，取消余额截图与排序；保留人工校准。
- 标注/运行时模型不自动替换；裁判切换整表重判。标注更换须负责人确认并整批重标。
- 最新主流程表仍列公开中文的原标注组合；合成批次沿用负责人随后授权的替代组合，不将其伪称方案原表组合。
- 方案局部标题仍写腾讯平台；执行采用最新明确的腾讯与 Ark 双渠道规则。部分回填按本轮用户补充指令执行。指标、数据切分与验收阈值保持冻结。

## 裁判预检池与正式执行边界

| 数据表 | 主裁判（预检层） | 备选（预检层） | 当前状态 |
| --- | --- | --- | --- |
| public-chinese | Ark / glm-5-2-260617（Zhipu） | TokenHub / hy4-preview（Tencent）；TokenHub / glm-5v-turbo（Zhipu） | 缺 0 个备选；人工校准待完成 |
| synthetic-timeline | Ark / glm-5-2-260617（Zhipu） | TokenHub / glm-5v-turbo（Zhipu） | 缺 1 个备选；人工校准待完成 |

公开中文表的预检选择已冻结；合成表仅冻结目前合格候选与顺序，**未满足完整池要求**。同一备选厂商相同不违规，但渠道切换不算厂商独立。HY4 参与合成标注，因此不能作为合成表裁判。公开池当前限使用 DeepSeek+MiMo 标签的 DuLeMon 表；PerLTQA 作者原始标注厂商未核实，正式使用前须单独核对。

全部入选候选均有完整预检证据及本轮实际判分重复调用。格式预检与简单重复一致不代表真实判分质量；**目前均未人工校准，主备均不得生成正式结果**。入口按表核对厂商、预检/调用证据哈希、提示词哈希与人工校准，不再查询余额。GLM-5V-Turbo 已处于预下线状态；[腾讯公告](https://cloud.tencent.cn/announce/detail/2479)给出下线时间，正式执行前需重新核对可用性。

本轮新增候选复测：

| 模型/渠道 | HTTP 状态统计 | 实际关闭思考 | 结论 |
| --- | --- | --- | --- |
| Ark / glm-4-7-251222 | {'404': 1} | 否/未能验证 | 不通过 |
| TokenHub / glm-5.2 | {'402': 1} | 否/未能验证 | 不通过 |
| TokenHub / mimo-v2.6-flash | {'402': 1} | 否/未能验证 | 不通过 |
| TokenHub / minimax-m2.7 | {'200': 1} | 否/未能验证 | 不通过 |
| Ark / mistral-7b-instruct-v0.2 | {'404': 1} | 否/未能验证 | 不通过 |

GLM-5.2 腾讯渠道与 MiMo Flash 的额度错误仍在；MiniMax 虽能返回，但产生 32 个思考 token，不符合要求。Ark GLM-4.7 当前不可调用。未充值、未开后付费、未把失败候选凑成备选。

调用量按当前查询集估算：题数 2250，实验组 4，重复 3；判分 27000 次，答题 27000 次，合计 54000 次。判分输入/输出估计 27000000/2700000 token，合计 29700000；这是方案单次用量假设，非余额或实际全评测消耗。切换整表重判会增加消耗，按实际调用台账另报。

本轮实际调用 20 次，服务商已报告 token 总量 2250；错误响应无用量时不假设免费。模型预检控制参考[腾讯思考文档](https://cloud.tencent.com/document/product/1823/131208)与 [Ark 参数说明](https://docs.volcengine.com/docs/ark/model-parameter-support?lang=en)。模型/版本和各次用量详见实际调用 JSON。

跨渠道模拟：注入 402 后丢弃腾讯的 2 条部分判分，Ark 从头完成 3 条；正式结果只含一个模型/版本。该演示真实运行入口与 HTTP MockTransport，真实模型调用 0 次，不算正式评测或人工校准。

## 合成时间线一致性审计

结论：**流程验证，不作质量证据**。新批次共有 1630 条，两模型一致 1630 条，一致率 100%、κ=1.0；未重标或混入历史标签。

审查实际归档请求 66 份，用户载荷内发现显式答案/构造标签字段 0 处，原始构造 ID 暴露请求 0 份。输入含来源正文和候选，标准答案/问题/时间线元数据未发送；输出 schema 提到 label 属于任务说明，不等于泄漏答案。

但是：仅凭来源轮数、不看候选语义，就能吻合 1630/1630 条；仅凭原始位置可吻合 1630/1630。原始排列标签只变换 1 次；全部 66/66 批次标签单一；负样本来源文本只有 1 种。构造器直接生成可被来源支持的事实与明显不受支持的负样本，任务过易且结构/顺序与标签完全混杂。

离线捷径检查能证明数据存在混杂，不能断言模型实际用了哪个捷径。未额外调用模型做反事实实验。后续应新建独立困难集，平衡来源长度、打乱顺序/ID、加入归属和临时性难例、隐藏构造真值，做打乱/遮蔽/语义反事实对照并人工抽检；**本轮只给方案，未擅自改冻结数据或重新标注**。详情见[请求级审计](synthetic-leakage-audit.json)。

## 中文查询集

生成 2250 条，覆盖 795 个来源上下文；按原会话切分继承，dev 693、test 1557，未重新分配旧数据。切分比例按来源冻结并非对查询强行重切。证据编号均可映射至冻结来源的轮次/记录/会话；检索上下文不含查询、答案、原生人设标签。无真实模型调用。

| 题型 | 数量 |
| --- | --- |
| abstention | 250 |
| knowledge-update | 250 |
| multi-session | 250 |
| preference | 250 |
| single-session | 1000 |
| temporal-reasoning | 250 |

来源：DuLeMon 500 条（真实人设对话衍生，父仓库 Apache-2.0，归档无单独许可）、PerLTQA 中文原生问答 1000 条（作者模型生成/修订，CC BY-NC 4.0，非商业并保留署名）、原合成时间线 750 条（复用原题，不伪称新增真实对话）。公开来源链接、提交和数据哈希见[清单](query-manifest.json)。

规模和题型下限满足，**质量闸门未通过**。真实人工对话衍生仅 500 条；PerLTQA 不能算真人对话，合成部分继续只作流程验证。不把总查询数计入真实中文记忆金标规模。原生标签可能有噪声，偏好/拒答改写未完成人工核验；只保留原二元相关性，未伪造分级相关性标签。准备的查询抽检 225 条仅本地暂存，本轮不催负责人填写。

当前数据路径：`.local/phase1/round3/followup/chinese-queries-v1-ready/`。原数据不入 Git，不发群。抽样种子、已有会话切分哈希、每个文件哈希已记录。DuLeMon-SELF 的 24500 段缺少 BOTH 所需的 said/no-said schema，因此本次派生查询不使用它们，不把缺字段等同于负例。

## 人工回填与 ECD

DuLeMon 模板仍为 230 条，当前收到的新负责人回填 0 条，一致率尚无。用户所说“约核对若干行”不是已收到的结果，未代填数字或人工标签。脚本支持原表全行保留、未核对人工栏留空；只对实际有效填写的行计分，并报告样本覆盖与部分审核局限。先算冻结参照一致率，低于 95% 只采用人工确认子集并重算记忆点；不会先纠正参照再制造高一致率。缺一半的人工字段、重复 ID、被改来源即拒绝。旧 Agent 标签无自动导入路径。

当前可宣称的负责人确认真实中文金标准为 0，距目标 1500；原生待核验应记参照 1746 个，不能混称人工确认。ECD 120 段表和原审核包全部逐字节保持，继续等待负责人另行标注；未生成旧仲裁包。

## 验证、运行与遗留

完整四道门：pytest 359 passed（18.16 秒）；ruff、mypy strict、foundation 全通过，见[原始验证日志](validation.log)。真实 Docker 集成测试纳入此次全量运行。手算指标定义、阈值配置和旧切分文件哈希核验未变。

复现命令（输出必须选新的 `.local` 目录，避免覆盖冻结记录）：

```bash
uv run python scripts/build-chinese-queries.py --normalized .local/phase1/normalized-v3 --timeline .local/phase1/timeline-v1 --output .local/queries-new-run
uv run python scripts/audit-synthetic-leakage.py --timeline .local/phase1/timeline-v1 --campaign .local/phase1/round3/closeout --output .local/leakage-new-run.json
with-llm uv run python scripts/preflight-judge-pool.py --mode candidate-preflight --output .local/candidate-preflight-new-run
with-llm uv run python scripts/preflight-judge-pool.py --mode judge-repeat --output .local/judge-repeat-new-run
uv run python scripts/run-judge-table.py --demo-cross-provider --output .local/cross-cloud-new-run --table-id public_chinese_demo
bash scripts/check.sh
uv run python scripts/report-phase1-followup.py
```

预检复现会产生真实调用；构建、审计和模拟不会。数据重建需按清单下载私有本地原始数据，仓库不附原文。

未完成：合成表第三个合格裁判候选；所有主备真实人工校准；DuLeMon 实际负责人回填；中文查询人工质量/分级相关性审核；合成困难集与反事实实验；ECD 另行人工标注。阶段 1 仍未通过，不进入阶段 2。可另行按项目目录整理为飞书文档，写入前确认标题、内容范围、目录和身份。
