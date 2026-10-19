# agent-memory 阶段1：模型迁移与标注交接

执行：Codex；生成日期：2026-10-19（北京时间）。

来源：agent-memory@db3f264；未提交修改：False。

**阶段1尚未通过验收，未进入阶段2。** 本报告是阶段内交接，不是最终质量结论。

## 新版模型

用户已确认Ark抽取/答题改为doubao-seed-2-1-pro-260915。向量模型保持不变。

| 模型 | 格式样本 | 5次一致 | 预检通过 |
|---|---:|---|---|
| doubao-seed-2-1-pro-260915 | 100/100 | True | True |
| deepseek-v4-pro-0813 | 100/100 | True | True |
| minimax-m2.7 | 100/100 | True | True |

实际LLMExtractor最小合成请求200、1条候选、scope正确、没有降级；这不等于质量达标。

## 完整标注与待人工审核

| 数据 | 候选条数 | 双标注完整 | 一致性与人工材料 |
|---|---:|---|---|
| synthetic-timeline | 1630 | True | κ=0.929；分歧18；盲审163；待人工 |
| public-chinese | 1648 | True | κ=0.848；分歧114；盲审165；待人工 |

两份盲审JSONL中的human_label/human_reason均为空，必须由负责人填写。
模型κ门槛仍为0.7；负责人已明确批准10%盲审一致率至少95%；须用真实人工回填计算，不由助手代签。

## 复现

模型预检与标注入口见docs/evals/README.md；批次原文/响应/重试账本保存在.local/phase1。
本报告由scripts/phase1-rotation-report.py自动生成；JSON保留数据/标签散列与限制。

## 局限

- Human arbitration/audit and judge calibration are not performed by the assistant.
- Synthetic templates are not evidence of real Chinese task quality.
- Public Chinese candidates are not approved gold; final accepted facts may be below target.
- Known failed/cancelled historical calls remain in .local; unknown delivery/usage is not zero.
- Model roles/prompts/batch sizes differ across datasets and are frozen separately.
- Public Chinese question generation/type coverage and other phase1 gates remain unaccepted.
- Original phase1 delivery and B0 tag remain historical, unchanged artifacts.
