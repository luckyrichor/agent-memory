# B0独立公网压测核验（失败结果）

固定B0@1e9d6f3，腾讯原生1024维，完全虚构32字符性能语料；TX2独立发压、TX隔离服务。每规模3轮、1QPS，每轮60秒预热+300秒测量。

| 记忆数 | 测量请求 | 失败 | 失败率 | 95%重复级区间 | 每轮客户端p95约 | 丢弃到达（含预热） |
| --- | --- | --- | --- | --- | --- | --- |
| 10000 | 867 | 557 | 64.24% | 60.35%–67.13% | 30.00秒 | 33 |
| 100000 | 888 | 869 | 97.86% | 97.11%–98.69% | 29.99秒 | 33 |

两端资源采样完整，发压端资源均合格；所有运行均有丢弃到达，不能通过1QPS可持续容量验收。

异常日志完整虚构查询正文命中58次，所检查的API密钥命中0次。正文出现在取消查询异常的SQL参数中，SC4未通过。报告只给聚合数字，原始异常和文本留在服务器私有目录。

Exact27 resamples of3 independent API-process repeats with replacement; percentile95% interval. n=3 has low precision. Latency CI is the mean of per-repeat p95s, not a pooled per-request p95 CI.

- Use error count/request count, not the k6 Counter rate field, for error fractions.
- All six load-host resource checks pass, but every run dropped arrivals; no sustainable1QPS capacity claim.
- Slow lexical SQL and pool exhaustion are observed; this is not proof of a single root cause or an optimization result.
- Server status and SQL logs include warmup and shutdown; client timeout and later server response counts cannot be directly equated.
- Canceled query exceptions during cleanup can serialize SQL parameters containing full fictional queries. This fails the body-log requirement even though no real user conversation was used.
- Both machines are in ap-shanghai. Independent-host public ingress was tested; cross-region path was not.
