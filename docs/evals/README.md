# 阶段1：评测框架与数据

日期：2026-10-19（北京时间）。执行：Codex。开发模型具体版本未核实。
原方案：[agent-memory面试级完善方案](../agent-memory面试级完善方案.md)；本目录只说明阶段1实现，不改变原目标与阈值。

## 这次代码负责什么

1. 数据归一化与原件/结果哈希；保留来源单位、角色、时间、协议与异常。
2. 公共API/SDK直写或对话事件摄取；独立工作区隔离每段历史；检索结果映射回来源。
3. 检索RT1～RT6的已有结果评分、分题型、会话级bootstrap与配对对比；不可覆盖结果目录。
4. 命名的计数、比例、微F1、延迟、用量等公式及可手算单测。
5. 腾讯模型真实预检；模型独立标注、受限本地重放缓存、无正文的调用账本、盲审材料导出。

注册66个指标编号不等于66项实验已完成。完整B0、外部三基线、压力/故障/安全专项实验属于后续阶段；当前没有把未采集的观测值写成0。

## 获取与归一化数据

所有原文/标签/模型完整答复留在Git忽略的`.local/`，公共仓库只放来源与哈希。首次下载须核对官方协议。

```bash
mkdir -p .local/phase1/data
cd .local/phase1/data
git clone --depth 1 git@github.com:snap-research/locomo.git
git clone --depth 1 git@github.com:Elvin-Yiming-Du/PerLTQA.git
curl -fL https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/main/longmemeval_oracle.json -o longmemeval_oracle.json
curl -fL https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/main/longmemeval_s_cleaned.json -o longmemeval_s_cleaned.json
curl -fL https://dialogue.bj.bcebos.com/Knover/DuLeMon.zip -o DuLeMon.zip
cd ../../..
uv run python scripts/prepare-eval-data.py --root .local/phase1/data --output .local/phase1/normalized-new
```

在tx访问境外HTTPS可能需要按环境文档配置代理；模型请求本轮直接连接、不经环境代理。

来源：[LongMemEval](https://github.com/xiaowu0162/LongMemEval)、[LoCoMo](https://github.com/snap-research/locomo)、[PerLTQA](https://github.com/Elvin-Yiming-Du/PerLTQA)、[DuLeMon](https://github.com/PaddlePaddle/Research/tree/master/NLP/ACL2022-DuLeMon)。
LoCoMo/PerLTQA CC BY-NC 4.0；LongMemEval MIT；DuLeMon压缩包没有独立许可证，清单保留总仓库Apache-2.0与数据授权不单列的限制。

注意：

- S/oracle都以同一个question_id标识一段历史，衍生版本共用切分。按会话数量30%/70%、seed42，小集合四舍五入；公共基准原件可能复用来源片段，需要另外核对跨组来源交集，不能仅凭不同question_id宣称没有污染。
- LoCoMo的13道题含未解析证据；导入不猜改它们，评分显示`unavailable_gold_evidence`。不能在忽略这些题后声称覆盖全部公开题。
- LoCoMo是两个人类角色，不强行转换成user/assistant。PerLTQA是来源记录，全文模式需先给出可信角色/时间映射；目前直写可用，全链路对不具备角色的记录明确拒绝。
- DuLeMon按self/both保留原人设、说话人和轮次标注；原人设不是检索正文，不把答案写入索引。
- LongMemEval时间无时区，导入器为可解析时间显式假定UTC；本假设只能用于保留相对时间，不能外推真实用户时区。
- 文本超过4000字符拆片，不丢尾部；来源映射记录每片，空文本不写入。

## 单条评测命令

使用隔离的评测服务与专用工作区。复制`system-config.example.json`到.local，给每段会话分配不同且JWT已授权的空工作区。配置只写环境变量名，不写真实凭据。

```bash
uv run python -m agent_memory.evals.experiment \
  --dataset .local/my-eval-subset.jsonl --mode direct \
  --config .local/my-eval-system.json --metrics RT1,RT2,RT3,RT4,RT5,RT6 \
  --output .local/results/YYYY-MM-DD-实际提交-数据集
```

full模式通过SDK写conversation.message，需要服务的dispatcher/extraction worker已经启动；工具不替用户启动生产服务或变更抽取模型。配置中提供精确extractor_version与受限观察者身份，数据库URL从MEMORY_EVAL_DATABASE_URL读取。
full仅在同一版本的全部事件任务成功后评分，dead或等待超时明确报错。可能合法抽取0条，不用来源原文填补抽取结果。

由于当前公共API尚未暴露完整证据链，full模式有一条明确的**内部评测观察通路**：只读Event→Evidence→Version ID，不读取正文，连接必须是非属主、非superuser、NOBYPASSRLS，并使用租户RLS。此例外只用来测内部血缘；实际写入与搜索仍走公开API。与阶段4的产品证据引用返回不是一回事。

如果已有外部采集的逐题结果，可只评分/配对：

```bash
uv run python -m agent_memory.evals.runner \
  --dataset .local/my-eval-subset.jsonl --predictions .local/predictions.jsonl \
  --mode direct --config .local/my-eval-system.json --metrics RT1,RT2,RT3,RT4,RT5,RT6 \
  --output .local/results/新的不可覆盖目录
```

预测每行格式：`{"question_id":"原ID","ranked_source_ids":["来源ID"]}`；排名必须来自实际运行，不允许拿金标当预测。
配对增加`--baseline 旧结果/report.json`，要求数据哈希一致。缺题、不匹配ID、缺证据、未定义分母分别记录，不默认为正确。

### 评分单位与统计

RT1是查询至少命中一条证据；另报evidence_coverage，不能拿覆盖率替代查询命中率。SDK采集同时保存每个记忆的证据集合，合并记忆可引用多来源，同源的不同记忆不挤掉排名槽位。RT2按前k条记忆的来源相关性判命中并除以k，缺失位置保留在分母；RT3按第一条相关记忆排名计算。只有来源证据标签时，不能推断整库每条记忆的分级相关度，因此主评分的RT4明确不可用；纯来源排名的兼容输入可算**来源单位**nDCG，报告单独标明单位，不混合聚合。

来源相关度不等于抽取事实正确性，EX1～EX5仍须独立金标。没有证据的拒答题单独RT6，目前只支持空结果判据，没有擅自添加低置信阈值。

比例CI用会话为重采样单位、1000次、95%；每个比例显示实际分母，n为会话重采样单位数。延迟采用(n−1)p线性插值；只有少量样本时p99不可靠，不能称生产尾延迟。
自动配对的增加/降低清单只表示分数方向；低值更好的错误率要结合指标方向解读。配对函数当前按问题ID重采样，不作为多问题会话数据显著性的最终依据。

## 可复现的公开语料冒烟

```bash
uv run python scripts/public-retrieval-smoke.py \
  --normalized .local/phase1/normalized-new --output .local/phase1/public-smoke-new
```

工具只创建临时Docker PostgreSQL，迁移到0008，创建非属主角色，生成临时JWT，经实际SDK/API写入与查询后销毁容器。每个公开集只取seed42开发集第一段有问题的历史；仅词法/结构化，未配置向量模型、无模型调用、ASGI进程内传输。它回答“导入与评分能否联通”，不回答B0总体质量或服务容量。

## 模型与标注

```bash
with-tencent uv run python -m agent_memory.evals.model_preflight \
  --output .local/phase1/preflight-new --prompt docs/evals/prompts/preflight-v2.txt
uv run python scripts/prepare-timeline-review.py --output .local/phase1/timeline-new
with-tencent uv run python -m agent_memory.evals.annotate \
  --items .local/phase1/timeline-new/items.jsonl --model deepseek-v4.1-flash \
  --cache .local/phase1/annotation-cache --output .local/phase1/annotation-A-new
```

B模型单独调用minimax-m3，不给它A的结果。每个模型先通过预检才能用于标注。预检是合成精确匹配任务，不是问答裁判校准；真实模型调用/格式/温度参数接受，不代表温度在供应商内部严格确定。

`annotate`保留prompt哈希、真实usage、每次HTTP状态、发送文本条数/字节数、重放标志；缓存包括provider、模型、输入和参数。命中重放不重复算真实调用/tokens。原始输入输出仅存受限.local目录，账本不含正文/密钥。调用失败或ID缺漏停止，不产生COMPLETE标记。

合成时间线覆盖六类查询各250条，430会话、130闲聊负样本、1500正向候选事实。它只是一份**待人工审核的模板化合成样本**；不能当作真实中文分布，也没有覆盖全部冲突/去重/敏感/注入专项要求。
[标注指南](labeling-guide-v1.md)说明keep/discard/uncertain、主体归属、时间条件和盲审规程。`labeling.review_pack`要求两边ID完全一致，计算模型间κ，导出不显示任何模型标签的仲裁和10%抽检表；人工标签由负责人填写，助手不能代签。

## 本阶段验收状态

以`docs/reports/phase1-*/delivery.md`为准。没有真实人工仲裁/盲审前，阶段1不标通过；仅有代码单测不等于模型/数据闸门通过。后续仍需补齐公开中文金标、专项集、全部复合指标观测适配与完整检索口径。

## 其他阶段1候选数据

`prepare-public-chinese-review.py --archive .local/phase1/data/DuLeMon.zip --output .local/phase1/public-chinese-new`：从BOTH训练文件seed42抽原始对话，保留分词与角色，原始人设只是待审核候选；助手单侧负样本作为派生片段单独声明，衍生样本与来源会话共享切分。

`prepare-specialist-review.py --output .local/phase1/specialist-new`：生成冲突300、去重500、敏感500（正常200）、注入200、污染100、隔离100的模板候选。每一条带未确认标记；满足候选数量不代表满足人工确认、语言覆盖或实际演练闸门。去重全部人工确认、冲突分类、敏感场景覆盖等仍需负责人审阅与补充。

这些文件不自动变成CI质量金标。现有CI会执行新增公式/导入/账本回归与原有foundation安全闸门；完整质量回归需在人审金标冻结后接入，不能用模板自证。

Ark预检记录区分“模型家族名”和实际调用ID。批量input收到HTTP200不代表返回多个独立向量；本轮两段文本仍收到单个1024维向量，不能据此实现独立文本的批量写入。接口与最大输入以[官方API](https://console.volcengine.com/ark/region:cn-beijing/docs/multimodal-vectorization-api)及[模型列表](https://docs.volcengine.com/docs/ark/model-list?lang=en)核验；SDK/聚合多模态接口不能混成同一种批量语义。

## 2026-10-19 经用户确认的模型迁移

当前角色配置见 [model-roles-v2.json](model-roles-v2.json)。用户已确认抽取/对话及端到端答题改用Ark `doubao-seed-2-1-pro-260915`；原始用户方案与旧404报告保持原样，B0源码标签不改。向量模型仍为`doubao-embedding-vision-251215`、1024维，不因对话模型变化重建向量空间。

新模型须有完整预检报告；最小200不能代替100格式样本、5次一致性或真实任务校准。TokenHub模型耗尽时选择通过预检的其他模型，并保持标注、裁判厂商独立。不同模型/提示词的部分标签不拼接成同一个冻结实验。

运行阶段1的抽取worker/API等命令时，可以显式使用新版配置：

```bash
with-ark uv run python scripts/with-phase1-runtime.py COMMAND [ARGS ...]
```

该入口从共享Ark授权环境读取密钥，仅给目标子进程设置`MEMORY_EXTRACTION_MODEL/ENDPOINT/TOKEN/TRUST_ENV`，不把密钥写入文件或输出，不自动启动服务。它覆盖目标进程的旧抽取配置；不改其他进程或历史B0记录。阶段2正式量化基线尚未建立，后续须用同一新配置重新测全部比较组，不把换模型后的结果直接与旧模型部分结果比较。

标注的`--deduplicate-sources`必须配合annotation-v4：完整来源只在sources表出现一次，source_ref逐条关联，无摘要/截断。它改变请求序列化与提示词版本，新运行须冻结新清单。显式`--retry-invalid-cache`保留每次原始失败响应，另存新响应；缓存回放不重复计用量。HTTP失败不能写成负标签。

若标注吞吐不足，可显式使用`--shards 2`等有界协程。它保持每个请求的批次边界和缓存键，仅改变调度次序；新父目录保存并发清单。必须全部子任务完成、ID精确覆盖才生成父COMPLETE。重复启动应使用新输出目录和原缓存，不能覆盖历史结果；取消时在途调用的未知用量须在报告列出。
