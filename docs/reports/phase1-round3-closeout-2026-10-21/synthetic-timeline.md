# 合成时间线整批重标独立报告

日期：2026-10-21；Codex；源码 db349e6。

目标 1630 条；新批次完成=True。输入、切分和提示SHA见JSON。原模型402部分批次只留历史，负责人已授权替换并整批重标。

|批次|模型|渠道|有效标签|剩余|完成|
|---|---|---|---:|---:|---|
|已停止历史|deepseek-v4-pro|TokenHub|1000|630|False|
|已停止历史|mimo-v2.6-flash|TokenHub|1050|580|False|
|替代新整批|deepseek-v4-pro-ga-260813|Ark|1630|0|True|
|替代新整批|hy4-preview|TokenHub|1630|0|True|

新组合全量κ与一致性：{"n": 1630, "agreement": 1.0, "kappa": 1.0, "matrix": [{"left": "discard", "right": "discard", "n": 130}, {"left": "keep", "right": "keep", "n": 1500}]}。共同保留 1500 条，含分歧/uncertain 0 条；10%抽检参照规模 163。人工字段未填写，审核未通过，本轮仍只要求负责人填DuLeMon230。

新旧标签不混用；新批次请求的实际model/version、usage及HTTP状态统计见JSON。仅合成数据，不计真实中文规模。标注厂商变动已同步正式裁判厂商排除；裁判额度排序等待截图，不充值或开启后付费。
