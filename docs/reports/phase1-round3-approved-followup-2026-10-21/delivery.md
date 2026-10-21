# agent-memory 阶段1：获批补量路径与查询版本启用

🤖 由 Codex 生成 · 2026-10-21 · agent-memory@7c112c4 · 未提交源码修改：False

**阶段1仍未验收，不进入阶段2。** 本报告由 scripts/report-approved-followup.py 生成；审核数据仅服务器本地和负责人私聊，仓库不含对话本体。

## 新版方案与差异

已完整重读最新版原件并另存 `docs/plans/2026-10-21-agent-memory-interview-plan-v2.md`，保留 @sh6_apple 原署名。新文件 SHA256 `da1126e8e77b5b91835cfc6b9849dd4915e1bdaba7524c7774c8fd09312c58e9`；旧文件保留，SHA256 `a199f472d908a603df158e2452ce8b58ef36210e8ff9a308273327e41b5d299d`；逐行差异见 plan-diff.patch。

新增：真实中文金标过关下限 700、目标 1500；明确独立盲抽 72 且最多错误 3；困难查询替换获批；裁判至少 1 个合格备选。

文件内部尚有旧文：第7节角色表仍写至少两个备选，标题/表格仍只写腾讯渠道；按本轮明确指令及新版选择规则执行至少一个备选、允许Ark、按每张数据表排除厂商。原件不擅改。通用负责人95%门槛仍保留，本次特批72条按最多3个错误执行，不改其他审核阈值。

## 独立盲抽与交付

冻结共同保留 711，扣除人工否定 1 后为 710。其中已被负责人确认的 19 条不重复送审；未审核总体 691 中，以新种子 20261022 简单随机不放回抽 72 条，再打乱展示顺序。与此前人工核对项重叠 0；覆盖 70 段对话。不是从全部剩余池不加区分抽样；已确认项属于已知层，未知层单独随机抽检。

格式最初提供虚构预览，负责人否决后明确指定沿用原八列并授权直接发送。现已严格采用：`item_id, conversation_id, subject, candidate, source, record_sha256, human_label, human_reason`。item_id是不透明随机编号，映射只留本地；source保持原JSON逐轮结构，未摘要、未拼成文本；人工两栏空白，模型标签/参照/类别提示不进入表。

真实表已私聊交付负责人，CSV SHA256 `24620c12a6f88a883d8615848612ac1bced3eec6d7c7c6435fdf8a5de47980c4`。已用接收器验证空白行、记录哈希、来源与候选逐字不变；完整JSONL和匿名映射本地保留。未向群发送真实表，先前虚构预览不是审核数据。

| 原始来源 | 条数 |
|---|---:|
| dulemon-both-train | 72 |

### 描述性类别分布

| 描述性类别 | 条数 |
|---|---:|
| family | 7 |
| other | 41 |
| preference | 15 |
| residence-origin | 4 |
| work-education | 5 |

类别只按候选文本的固定正则、首条命中互斥归类；用于分布描述，不是人工/模型金标，不向审核者显示。原始来源train是数据包来源名，不代表重新划分本项目开发/测试集。

### 人工回填、置信区间与后续门槛

当前未收到本次 72 条的人工回填，错误数、通过状态、错误率及置信区间均为空。回填必须完整；discard或uncertain均不视为正确keep，最多 3 条非keep才通过。不得用模型答案、构造规则或此前旧标签充人工。

回填后报告未知层有限总体的95%双侧等尾超几何精确区间，再结合已确认层加权到剩余池；同时给出观察错误率。分子/分母和先前已确认层单独报告。通用实验指标仍沿用原会话级bootstrap；本次有限总体审核区间方法明确单列，不改变指标公式。区间上界可能高于5%，这是不确定性，不擅自把“上界≤5%”加为新门槛，也不把“≤3错通过”说成统计证明真实错误率必≤5%。

当前已确认应记仍为 22，离新下限 700 缺 678，离目标 1500 缺 1478。这是已确认子集的确切数量，不是对全量的随机估计，不能给这个固定数编造置信区间。新池尚未通过，未计入金标；抽检通过后才报告其实际采用规模及抽检区间。

增量DuLeMon取样尚未开始：按批准顺序，先等抽检通过，再从未使用且有所需字段的对话固定种子补量，继承冻结切分、完整记录已用清单和所有对话分母。只计实际新增且通过抽检的记忆点；标注模型保持deepseek-v4-pro与mimo-v2.6-flash，失败保留进度并请求负责人确认更换。整段负样本会话尚未人工确认，不能由若干候选discard推定完整负例；会话数与负样本比例闸门仍待满足。

## 新版中文查询已启用

当前版本 `chinese-queries-v2-hard`：2250 查询、745 段来源；替换三类共 750，其他 1500 逐题核验保持。注册入口 `docs/evals/chinese-query-current.json`，数据SHA256 `a7a25b616c495988b2921f1d5981df4a1bc9d13c708c60452077020570dfb32a`，可生成普通评测入口可读的corpus.jsonl。

| 题型 | 数量 | 口径 |
|---|---:|---|
| abstention | 250 | 按原来源口径解释，不外推真人质量 |
| knowledge-update | 250 | 流程验证，不作质量证据；阶段2单列 |
| multi-session | 250 | 流程验证，不作质量证据；阶段2单列 |
| preference | 250 | 按原来源口径解释，不外推真人质量 |
| single-session | 1000 | 按原来源口径解释，不外推真人质量 |
| temporal-reasoning | 250 | 流程验证，不作质量证据；阶段2单列 |

旧查询文件与旧切分原样保留。新数据集SHA与旧版不同，新旧不可同集比较；新困难会话使用该集合原有固定切分，其他来源继承原切分。新corpus SHA256 `2af07b8f1ef1f22264e25ed65dc5ff5d7a27e6119cdaba6a8ab3214baf9c783c`。

已在评分入口实现flow_only_by_type隔离：三类只进入流程分项，不进入质量总指标或配对质量差异；同集比较检查仍保留数据集哈希。这里只执行夹具测试验证隔离机制，未运行阶段2质量评测。困难集人工抽检继续暂缓，不催办。

## 裁判：至少一个备选

| 数据表 | 主裁判 | 预检通过备选 | 尚缺 | 正式运行 |
|---|---|---|---:|---|
| public-chinese | Ark/glm-5-2-260617 | TokenHub/hy4-preview | 0 | 待人工校准 |
| synthetic-timeline | Ark/glm-5-2-260617 | 无 | 1 | 备选不足，且待人工校准 |

公开表满足的是当前预检数量要求，主备均未完成人工校准，不宣称正式评分已就绪。合成表因Tencent也是标注厂商不能拿HY4当备选；GLM-5V预下线不回填稳定池。主备最低数量已同时接入策略文件、池加载器和运行入口，正式池不足会拒绝运行。

| 本轮补查 | 日期 | HTTP | 完整预检通过 |
|---|---|---|---|
| Ark/glm-4-5-air-20250728 | 2026-10-21T13:27:33.499663+00:00 | [404] | False |
| TokenHub/mimo-v2.6-pro | 2026-10-21T13:27:32.761272+00:00 | [402] | False |

本轮额外调用 2 次，均在首探失败后停止，错误响应没有usage，不能写成实际消耗为零。未查余额、未充值、未开后付费。未找到合成表合格备选；此前不能关闭思考、采样控制未证实或额度失败的候选不为凑数纳入。已有主备完整预检/实调证据保留引用前轮文件，未冒称本轮重跑。

## 验证与未完成项

完整四门：pytest 367 passed / 17.74s；ruff、strict mypy通过；foundation total=8 passed=8 failed=0 tenant_leaks=0 deleted_memory_hits=0。环境与原始验证日志见report.json、validation.log。

保护核验：ECD原审核表、原生DuLeMon审核表、旧查询、原指标定义和通用审核阈值哈希保持。新政策是负责人批准的单独版本，旧政策作为历史保留。

未完成：本次独立人工审核及采纳池、增量补量、整段负样本确认、合成表裁判备选、裁判人工校准。ECD和困难集人工审核仍暂缓；未代签。阶段1尚未验收，不进入阶段2。

## 复现与回填命令

### audit

```bash
uv run python scripts/prepare-approved-joint-audit.py --items .local/phase1/chinese-expansion-v2/dulemon/items.jsonl --left .local/phase1/chinese-guide-v2-full-fallback-resume1/dulemon/labels-deepseek-v4-pro-run1/labels.jsonl --right .local/phase1/chinese-guide-v2-full-fallback-resume1/dulemon/labels-mimo-v2.6-flash-run1/labels.jsonl --prior-human .local/phase1/round3/owner-hardset/native-audit-final/adopted-labels.jsonl --output .local/reproduction-joint72
```

### queries

```bash
uv run python scripts/materialize-current-chinese-queries.py --output .local/reproduction-queries-v2.jsonl
```

### finalize

```bash
uv run python scripts/finalize-approved-joint-audit.py --pack .local/phase1/round3/approved-followup/joint-audit-72-v1 --submitted OWNER_RETURN.csv --output .local/joint72-owner-result --reviewer OWNER_ID
```

### checks

```bash
bash scripts/check.sh
```
