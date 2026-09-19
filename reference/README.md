# reference/

外部参考材料，**不属于本项目的构建、测试或发布范围**。CI、`pytest`、`ruff`、`mypy` 都不覆盖这里。

## claude-prototype/

另一套独立的记忆系统原型（约 2000 行 Python），由另一个 AI 编码会话产出，与本项目**没有共享代码、不可 import**。搬进来是因为它承载了本项目缺失的**语义层设计思路**，是 Phase 3–5 的设计输入。

它探索而本项目尚未实现的东西：

- **两阶段提取**（`memory_extractor.py`）：阶段 1 看清单摘要生成候选（便宜、宽进），阶段 2 只对已存在的目标文件读全文做 `DUPLICATE / NEW / UPDATE` 判定（贵、准）。区分 `state`（属性有界，可读全文）与 `event_log`（无限追加，先用字符 bigram Jaccard 初筛）。
- **检索后的行级过滤**（`memory_retriever.py`）：路由选中文件、读出全文后，再筛出真正相关的行，而不是整份塞进 prompt。另有一条关键设计：行为类偏好（如"回复简洁点"）**不参与相关性过滤**，从固定路径无条件注入 —— 用相关性筛选它是文不对题的。
- **LLM-as-judge 评测**（`eval_harness.py`）：`must_contain` 子串检查 + LLM 裁判双层判定，同一用例跑 N 次统计通过率，避免"看一次输出就下结论"。含防注入场景。
- **多模型 fallback**（`llm_client_ark.py`）：同模型失败重试 3 次 → 换下一个模型；模型列表按省 token 优先排序。对应本项目 Phase 5 替换确定性提取器时要解决的问题。

代码注释里承载了大量"为什么这么设计"的推理，往往比代码本身长 —— 那才是这份材料的价值所在。

## 运行

需要 `ARK_API_KEY`（火山方舟）。密钥放在仓库根的 `.local/ark.env`，已被 `.gitignore` 忽略，**不要提交、不要打印其值**。

```bash
cd reference/claude-prototype
set -a; source ../../.local/ark.env; set +a
python3 demo_real_llm.py          # 真实 LLM 跑完整闭环
python3 test_race_condition.py    # 双进程竞态复现，不需要密钥
```

`memory_extractor.py` 和 `memory_retriever.py` 底部各带 `MockLLMClient` 的 demo，无需密钥即可运行。
