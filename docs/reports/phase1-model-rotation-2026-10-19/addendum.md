# 本次交接补充说明

负责人已确认盲审≥95%，模型κ≥0.7保持不变。阶段1仍未验收，阶段2未开始。

## 数据规模仍有缺口

- synthetic-timeline：候选1630条，两模型共同保留1482条；人工未确认，不视为金标准规模。
- public-chinese：候选1648条，两模型共同保留511条；人工未确认，不视为金标准规模。

公开中文抽取金标准仍未达到原目标，后续需在真实人工校准后补充样本。公开中文查询建设、自然负样本比例和裁判人工校准也不能用本次候选标注代替。

## 资格纠错与调用边界

先前Kimi格式预检成功不能证明采样参数生效；原方案排除Kimi，已停止并把所有Kimi结果排除正式标注、κ及审核包。完整审计见上一份报告目录的model-eligibility-audit-v1.json。旧探索/取消/失败记录保留在.local，不将其未知用量记零，也不宣称本报告是账户总费用统计。未开启后付费。

## 代码验证

源文件对应a2a8422：pytest 319 passed（16.1s），All checks passed!；Success: no issues found in 79 source files；Foundation evaluator: total=8 passed=8 failed=0 tenant_leaks=0 deleted_memory_hits=0。测试启动时含随后固化的源码修改，当前src/tests/migrations/锁文件与该提交相同。原件见.local/model-retests/human-review-final-*。

## 下一步需要真实负责人输入

审核包内CSV只填写human_label和human_reason，不能由助手代签。先仲裁，再做盲审；使用95%阈值与冻结参照计算一致率，不能先改标签再比较。没有收到回填时人工闸门保持待完成。
