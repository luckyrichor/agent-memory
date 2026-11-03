# B0补齐过程记录（未完成，不用于最终交付）

更新：2026-11-01T09:10:40.303775+08:00

业务版本B0@1e9d6f3；测量工具来自agent-memory@2fae08b及未提交修改。未进入阶段3。

| 项目 | 已核对结果 |
| --- | --- |
| 官方tokenizer | 390上下文；8次API usage文本差分核对均为0 |
| 100k跨Mac恢复 | passed；全表/1000随机行/32检索/角色RLS核对；环境差异见单项报告 |
| worker实际进程死亡 | 默认30秒租约，三次由替代worker接手；每版本向量1行 |
| 向量HTTP瞬态故障 | 超时/429/503各三次，退避后第二次成功；持续失败/死信仍待覆盖 |
| 数据库重启 | 三次共120确认写入无丢失；14次HTTP500与12次传输失败，错误语义仍是缺陷 |
| 日志/链路 | 未通过：公网压测异常日志完整虚构查询正文命中58次；所检查API密钥命中0次；外部收集器仍未覆盖 |
| 独立公网发压 | 六轮已核验；1万条失败557/867、10万条869/888，1QPS容量未通过；两端同上海，不代表跨地域 |

待完成：

- Extraction owner73 judgments validated and both judges pass by task. EX1/EX2/F1 sampled human metrics available; separate EX5 ownership sublabel calibration and extraction repeat stability remain uncovered.
- Complete PF coverage and capacity interpretation; timed runs are not automatically accepted.
- Remaining F1–F12 coverage and full pressure/fault logs; completed individual observations do not certify all reliability controls.

局限：

- DeepSeek is also one gold annotation vendor; same-vendor answer/extraction can slightly inflate extraction scores; joint retention by two vendors partly mitigates this.
- No new Ark/O10 model comparison because Ark has no quota; previous mixed-model results remain exploratory outside new B0.
- Capacity corpus is entirely fictional, real native vectors,100k unique32-character texts; it is not natural semantic benchmark quality or the full natural memory length distribution.
- Mac was explicitly authorized as an independent load host; physical cross-region placement is not independently verified.
- MiniMax cross-reference and MiniMax backup are the same model and are not independent.
