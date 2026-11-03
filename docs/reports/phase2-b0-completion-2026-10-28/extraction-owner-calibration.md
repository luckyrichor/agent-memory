# 抽取专项负责人校准（聚合）

73条全部对齐，原题、参考与答案未改，人工判定与理由完整；原始标签和理由仅在服务器私有目录。

| 裁判 | 分层 | n | 一致率 | Cohen κ | 判对但人工判错 | 采用门槛 |
| --- | --- | --- | --- | --- | --- | --- |
| glm-5.2 | overall | 73 | 94.52% | 0.8857 | 3/73 | 达标 |
| glm-5.2 | recall | 30 | 100.00% | 1.0000 | 0/30 | 达标 |
| glm-5.2 | precision | 43 | 90.70% | 0.8143 | 3/43 | 达标 |
| minimax-m3 | overall | 73 | 95.89% | 0.9148 | 3/73 | 达标 |
| minimax-m3 | recall | 30 | 100.00% | 1.0000 | 0/30 | 达标 |
| minimax-m3 | precision | 43 | 93.02% | 0.8608 | 3/43 | 达标 |

人工精确率EX1：21/43=48.84%；95%会话簇区间(0.2, 0.7222222222222222)。
人工召回率EX2：7/30=23.33%；95%会话簇区间(0.0, 0.48148148148148145)。
F1：0.3158。

Per-task kappa>=0.7 OR accuracy>=0.9. Failing task judge cannot supply formal metric; full owner judgments directly supply sampled human EX1/EX2.

- DuLeMon selected dev8 conversations only; not all dev data or a test-set estimate.
- EX5 wrong-subject sublabel is not separately calibrated by these binary validity/coverage judgments and remains diagnostic.
- Extraction judge repeat stability is not covered by QA100x3 results.
- DeepSeek is also a gold annotation vendor; same-vendor extraction can bias scores upward; joint two-vendor gold retention partly mitigates this.
