# B0裁判人工校准报告（阶段2未验收）

时间：2026-10-27T18:30:34.197735+08:00；agent-memory@2fae08b，含未提交修改；业务B0@1e9d6f3。

## 数据与方法

冻结开发抽样B0；校准300条按题型、系统组、原裁判正确/错误分层，来自同一1560实验行；人工0/1逐item_id关联、原文/答案/理由不改。非简单随机抽样，下面总体数指校准样本，不冒充全部开发集。95%区间用数据集+会话聚类bootstrap1000次，是固定分层样本内诊断。
对照：主裁判GLM5.2、备选MiniMax3对同一负责人人工标签；模型输入仅问题/参考/答案和冻结rubric，不给系统组、人工结果或理由。

## 主备裁判与混淆矩阵

| 裁判 | n | 准确率 | κ | 判0/人工0 | 判0/人工1 | 判1/人工0 | 判1/人工1 | 错判为对/全部 | 错判为对/裁判判对 | 采用门槛 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| glm-5.2 | 300 | 95.0000% | 0.897260 | 167 | 8 | 7 | 118 | 2.3333% | 5.6000% | 通过 |

glm-5.2 95%聚类区间：{"accuracy": [0.9219858156028369, 0.9808917197452229], "kappa": [0.839184508816121, 0.9608699781555703], "false_positive_over_all": [0.0, 0.05813953488372093], "false_positive_over_judge_positive": [0.0, 0.125]}。
| minimax-m3 | 300 | 97.6667% | 0.951844 | 173 | 6 | 1 | 120 | 0.3333% | 0.8264% | 通过 |

minimax-m3 95%聚类区间：{"accuracy": [0.9622641509433962, 0.9921259842519685], "kappa": [0.9190092020673138, 0.9841269841269842], "false_positive_over_all": [0.0, 0.013513513513513514], "false_positive_over_judge_positive": [0.0, 0.029411764705882353]}。

门槛按负责人本次明确口径：κ≥0.7或准确率≥90%；不适用此前更严的κ单闸门。本轮通过则不改提示词、不启动无必要的再校准；失败须版本化修订、整批重判并记录同批复用，最多三轮，仍失败改纯人工。

## 分题型、系统组与最差分层


### glm-5.2 / 题型

| 层 | n | 一致率 |
|---|---:|---:|
| 1 | 20 | 90.0000% |
| 2 | 16 | 100.0000% |
| 3 | 16 | 100.0000% |
| 4 | 20 | 100.0000% |
| 5 | 19 | 84.2105% |
| abstention | 16 | 100.0000% |
| dialogues | 32 | 84.3750% |
| events | 24 | 95.8333% |
| knowledge-update | 21 | 100.0000% |
| multi-session | 28 | 100.0000% |
| preference | 25 | 88.0000% |
| profile | 17 | 100.0000% |
| single-session-assistant | 18 | 100.0000% |
| single-session-preference | 12 | 100.0000% |
| temporal-reasoning | 16 | 93.7500% |

### glm-5.2 / 系统组

| 层 | n | 一致率 |
|---|---:|---:|
| full-context | 74 | 93.2432% |
| naive-vector | 88 | 94.3182% |
| no-memory | 60 | 93.3333% |
| system | 78 | 98.7179% |

### glm-5.2 / 题型×系统组

| 层 | n | 一致率 |
|---|---:|---:|
| 1/full-context | 8 | 87.5000% |
| 1/naive-vector | 4 | 75.0000% |
| 1/no-memory | 4 | 100.0000% |
| 1/system | 4 | 100.0000% |
| 2/full-context | 4 | 100.0000% |
| 2/naive-vector | 4 | 100.0000% |
| 2/no-memory | 4 | 100.0000% |
| 2/system | 4 | 100.0000% |
| 3/full-context | 4 | 100.0000% |
| 3/naive-vector | 4 | 100.0000% |
| 3/no-memory | 4 | 100.0000% |
| 3/system | 4 | 100.0000% |
| 4/full-context | 4 | 100.0000% |
| 4/naive-vector | 7 | 100.0000% |
| 4/no-memory | 4 | 100.0000% |
| 4/system | 5 | 100.0000% |
| 5/full-context | 5 | 60.0000% |
| 5/naive-vector | 6 | 83.3333% |
| 5/no-memory | 4 | 100.0000% |
| 5/system | 4 | 100.0000% |
| abstention/full-context | 4 | 100.0000% |
| abstention/naive-vector | 4 | 100.0000% |
| abstention/no-memory | 4 | 100.0000% |
| abstention/system | 4 | 100.0000% |
| dialogues/full-context | 8 | 100.0000% |
| dialogues/naive-vector | 8 | 87.5000% |
| dialogues/no-memory | 8 | 50.0000% |
| dialogues/system | 8 | 100.0000% |
| events/full-context | 4 | 100.0000% |
| events/naive-vector | 8 | 87.5000% |
| events/no-memory | 4 | 100.0000% |
| events/system | 8 | 100.0000% |
| knowledge-update/full-context | 4 | 100.0000% |
| knowledge-update/naive-vector | 5 | 100.0000% |
| knowledge-update/no-memory | 4 | 100.0000% |
| knowledge-update/system | 8 | 100.0000% |
| multi-session/full-context | 8 | 100.0000% |
| multi-session/naive-vector | 8 | 100.0000% |
| multi-session/no-memory | 4 | 100.0000% |
| multi-session/system | 8 | 100.0000% |
| preference/full-context | 8 | 75.0000% |
| preference/naive-vector | 8 | 87.5000% |
| preference/no-memory | 4 | 100.0000% |
| preference/system | 5 | 100.0000% |
| profile/full-context | 4 | 100.0000% |
| profile/naive-vector | 7 | 100.0000% |
| profile/no-memory | 3 | 100.0000% |
| profile/system | 3 | 100.0000% |
| single-session-assistant/full-context | 3 | 100.0000% |
| single-session-assistant/naive-vector | 6 | 100.0000% |
| single-session-assistant/no-memory | 3 | 100.0000% |
| single-session-assistant/system | 6 | 100.0000% |
| single-session-preference/full-context | 3 | 100.0000% |
| single-session-preference/naive-vector | 3 | 100.0000% |
| single-session-preference/no-memory | 3 | 100.0000% |
| single-session-preference/system | 3 | 100.0000% |
| temporal-reasoning/full-context | 3 | 100.0000% |
| temporal-reasoning/naive-vector | 6 | 100.0000% |
| temporal-reasoning/no-memory | 3 | 100.0000% |
| temporal-reasoning/system | 4 | 75.0000% |

**最差题型×系统层（小样本须看n）**：{"dialogues/no-memory": {"n": 8, "invalid": 0, "accuracy": 0.5, "kappa": 0.0, "confusion": {"judge0_human0": 4, "judge0_human1": 0, "judge1_human0": 4, "judge1_human1": 0}, "false_positive_over_all": 0.5, "false_positive_over_judge_positive": 1.0, "judge_positive_n": 4, "false_negative_over_all": 0.0, "adoptable_on_this_calibration": false}}
分歧题型计数：{"dialogues": 5, "5": 3, "1": 2, "events": 1, "preference": 3, "temporal-reasoning": 1}

### minimax-m3 / 题型

| 层 | n | 一致率 |
|---|---:|---:|
| 1 | 20 | 90.0000% |
| 2 | 16 | 100.0000% |
| 3 | 16 | 100.0000% |
| 4 | 20 | 100.0000% |
| 5 | 19 | 94.7368% |
| abstention | 16 | 100.0000% |
| dialogues | 32 | 96.8750% |
| events | 24 | 95.8333% |
| knowledge-update | 21 | 100.0000% |
| multi-session | 28 | 96.4286% |
| preference | 25 | 96.0000% |
| profile | 17 | 100.0000% |
| single-session-assistant | 18 | 100.0000% |
| single-session-preference | 12 | 100.0000% |
| temporal-reasoning | 16 | 100.0000% |

### minimax-m3 / 系统组

| 层 | n | 一致率 |
|---|---:|---:|
| full-context | 74 | 95.9459% |
| naive-vector | 88 | 95.4545% |
| no-memory | 60 | 100.0000% |
| system | 78 | 100.0000% |

### minimax-m3 / 题型×系统组

| 层 | n | 一致率 |
|---|---:|---:|
| 1/full-context | 8 | 87.5000% |
| 1/naive-vector | 4 | 75.0000% |
| 1/no-memory | 4 | 100.0000% |
| 1/system | 4 | 100.0000% |
| 2/full-context | 4 | 100.0000% |
| 2/naive-vector | 4 | 100.0000% |
| 2/no-memory | 4 | 100.0000% |
| 2/system | 4 | 100.0000% |
| 3/full-context | 4 | 100.0000% |
| 3/naive-vector | 4 | 100.0000% |
| 3/no-memory | 4 | 100.0000% |
| 3/system | 4 | 100.0000% |
| 4/full-context | 4 | 100.0000% |
| 4/naive-vector | 7 | 100.0000% |
| 4/no-memory | 4 | 100.0000% |
| 4/system | 5 | 100.0000% |
| 5/full-context | 5 | 80.0000% |
| 5/naive-vector | 6 | 100.0000% |
| 5/no-memory | 4 | 100.0000% |
| 5/system | 4 | 100.0000% |
| abstention/full-context | 4 | 100.0000% |
| abstention/naive-vector | 4 | 100.0000% |
| abstention/no-memory | 4 | 100.0000% |
| abstention/system | 4 | 100.0000% |
| dialogues/full-context | 8 | 87.5000% |
| dialogues/naive-vector | 8 | 100.0000% |
| dialogues/no-memory | 8 | 100.0000% |
| dialogues/system | 8 | 100.0000% |
| events/full-context | 4 | 100.0000% |
| events/naive-vector | 8 | 87.5000% |
| events/no-memory | 4 | 100.0000% |
| events/system | 8 | 100.0000% |
| knowledge-update/full-context | 4 | 100.0000% |
| knowledge-update/naive-vector | 5 | 100.0000% |
| knowledge-update/no-memory | 4 | 100.0000% |
| knowledge-update/system | 8 | 100.0000% |
| multi-session/full-context | 8 | 100.0000% |
| multi-session/naive-vector | 8 | 87.5000% |
| multi-session/no-memory | 4 | 100.0000% |
| multi-session/system | 8 | 100.0000% |
| preference/full-context | 8 | 100.0000% |
| preference/naive-vector | 8 | 87.5000% |
| preference/no-memory | 4 | 100.0000% |
| preference/system | 5 | 100.0000% |
| profile/full-context | 4 | 100.0000% |
| profile/naive-vector | 7 | 100.0000% |
| profile/no-memory | 3 | 100.0000% |
| profile/system | 3 | 100.0000% |
| single-session-assistant/full-context | 3 | 100.0000% |
| single-session-assistant/naive-vector | 6 | 100.0000% |
| single-session-assistant/no-memory | 3 | 100.0000% |
| single-session-assistant/system | 6 | 100.0000% |
| single-session-preference/full-context | 3 | 100.0000% |
| single-session-preference/naive-vector | 3 | 100.0000% |
| single-session-preference/no-memory | 3 | 100.0000% |
| single-session-preference/system | 3 | 100.0000% |
| temporal-reasoning/full-context | 3 | 100.0000% |
| temporal-reasoning/naive-vector | 6 | 100.0000% |
| temporal-reasoning/no-memory | 3 | 100.0000% |
| temporal-reasoning/system | 4 | 100.0000% |

**最差题型×系统层（小样本须看n）**：{"1/naive-vector": {"n": 4, "invalid": 0, "accuracy": 0.75, "kappa": 0.0, "confusion": {"judge0_human0": 3, "judge0_human1": 1, "judge1_human0": 0, "judge1_human1": 0}, "false_positive_over_all": 0.0, "false_positive_over_judge_positive": null, "judge_positive_n": 0, "false_negative_over_all": 0.25, "adoptable_on_this_calibration": false}}
分歧题型计数：{"1": 2, "events": 1, "preference": 1, "dialogues": 1, "5": 1, "multi-session": 1}

## 同批100条三次新判分自一致性

glm-5.2：{"planned_rows": 100, "new_repeats_per_row": 3, "complete_rows": 100, "changed_any_of_three_n": 3, "changed_any_of_three_ratio": 0.03, "pairwise_disagreement_n": 6, "pairwise_denominator": 300, "pairwise_disagreement_ratio": 0.02, "valid_repeat_calls": 300, "invalid_repeat_calls": 0}
minimax-m3：{"planned_rows": 100, "new_repeats_per_row": 3, "complete_rows": 100, "changed_any_of_three_n": 1, "changed_any_of_three_ratio": 0.01, "pairwise_disagreement_n": 2, "pairwise_denominator": 300, "pairwise_disagreement_ratio": 0.006666666666666667, "valid_repeat_calls": 300, "invalid_repeat_calls": 0}

变化比例=三次中任意一次不同的条目数/三次均有效条目数；另列三对判分两两不一致率。无效输出不算对错，也不算稳定。原B0判分不充作三次之一。

## B0使用范围、区间与局限

Reuse the completed same300 minimax-m3 cross-reference judgments under frozen v1, exact row_id join, no relabel/cherry-pick; backup and cross-reference are the SAME model, not independent evidence
No naive accuracy multiplier or global correction: outcome/type/system stratified calibration is not a simple random population sample; no unweighted300 CI claimed as full1560 system accuracy; original E1 kept with provenance and calibration attached
Judge calibration validates answer-grading reliability only; does not validate missing EX/LC/RT/CX/RL/SC/PF adapters or candidate activation
DeepSeek同时是金标准标注模型之一，答题/抽取与标注同厂商可能使抽取指标偏高，双厂商共同保留已部分抵消；ECD客服领域不代表一般对话；程序构造题只作流程验证
两模型交叉参照不能充当第二个独立MiniMax验证；MiniMax作为标注厂商的构造题仍不放行其作正式独立裁判。主裁判人工门槛通过不等于全部指标或阶段2验收通过。

## 未完成项

- independent cross-region PF host and measurements
- missing functional observation adapters and true tokenizer coverage
- phase2 acceptance; no automatic phase3
