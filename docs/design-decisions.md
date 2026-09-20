# 设计取舍

记录关键设计选择及其理由 —— 面试要能讲清楚的那些。每条写清**问题是什么、选了什么、为什么不选另一个、代价是什么**。

按时间倒序。

---

## D1　遥测字段白名单：把「日志不许含正文」从纪律变成类型错误

**问题**　系统的核心不变量之一是「日志和 CLI 输出不得包含 Event 正文或记忆正文」。但可观测性恰恰是最容易泄漏的地方：一句 `logger.info(f"stored {content}")` 就能绕过 RLS、JWT、作用域检查建立起来的全部访问控制，而它在 code review 里看起来毫无威胁。

**选择**　不提供能放正文的接口。`observability/fields.py` 维护一份字段名白名单（标识符、封闭词表、数值三类），日志、span 属性、指标标签共用它。`StructuredLogger` 没有自由文本的 message 参数，只有事件名 + 关键字字段；字段名不在名单里、值超过 64 字符、或者类型不是 UUID/str/int/float/bool，一律抛 `UnsafeTelemetryField`。

**为什么不选另一种**

- *正则脱敏/掩码*：只能挡住认得出格式的东西（邮箱、卡号），挡不住「用户的偏好是……」这类自然语言正文，而记忆系统里正文恰恰全是自然语言。而且脱敏是事后补救，漏一条就是泄漏一条。
- *靠 review 和约定*：有效期等于团队记性。三个月后加一个新的日志点，没人会回头翻这条约定。
- *只在 CI 加一个扫描脚本*：能发现字符串字面量，发现不了运行时才拼出来的值。

**代价**　加字段要改 `fields.py`，是一次显式的、会被 review 的编辑 —— 这是刻意的摩擦。另外 64 字符上限意味着长的 reason code 也会被拒，写码时得挑短名字。

**证据**　`tests/unit/observability/test_fields.py` 断言 `content`/`payload`/`message`/`text`/`body`/`draft` 这些名字**不存在**于白名单；`tests/api/test_observability_api.py` 与 `test_worker_instrumentation.py` 把导出的 span JSON 和日志字段整体搜一遍正文子串。

---

## D2　observability 作为叶子包，而不是 application 的一个端口

**问题**　仓库是六边形分层、依赖单向朝内。可观测性是横切关注点，放哪一层都别扭：放 `infrastructure` 则 `application` 不能用它（方向反了）；定义成 `application/ports.py` 里的 Protocol 则每个用例都要多一个构造参数。

**选择**　做成叶子包 `observability/`：它不 import `domain`/`application`/`infrastructure`/`api` 中的任何东西（只 import `config` 取设置），所以任何层引用它都不产生环、也不产生朝外的依赖。

**为什么不选另一种**　把 telemetry 定义成端口、由 DI 注入，理论上更纯，但要给四个用例服务、worker、middleware 各加一个构造参数和一套假实现，收益只是「可以替换遥测实现」—— 而 OpenTelemetry 本身就是那层抽象，再包一层是重复的。纯度换来的可测试性，用 in-memory exporter 已经拿到了。

**代价**　`application` 层出现了对 OpenTelemetry API 的编译期依赖。可接受：它是 API 包不是 SDK 包，未配置 provider 时是 no-op。

---

## D3　自持 tracer/meter provider，不劫持 OpenTelemetry 全局 provider

**问题**　`trace.set_tracer_provider()` 全进程只生效一次，第二次调用被忽略并打警告。库如果去设全局 provider，既会和宿主进程已有的配置打架，也让测试无法替换。

**选择**　`tracing.py` / `metrics.py` 各自持有模块级 provider 引用；未设置时回退到全局。`set_tracer_provider(None)` 复位。

**代价**　第三方自动 instrumentation 挂在全局 provider 上，不会自动汇入我们的 provider。当前没有用自动 instrumentation，所以还没有影响；真要接 OTLP 时需要重新审视这个选择。span 之间的父子关系不受影响 —— 上下文传播走的是 context，与 provider 无关。

---

## D4　HTTP 指标用路由模板而不是具体路径

`/v1/memories/{memory_id}` 而不是 `/v1/memories/9f3c…`。具体路径里带记忆 ID，会让指标标签基数随记忆数量线性增长，把时序库打爆。代价是丢掉了「哪条记忆被读得最多」这种信息 —— 那属于业务分析，应该从审计表查，不该从监控指标里推。

---

## D5　关联 ID 在日志发出时捕获，而不是格式化时

`JsonFormatter.format()` 有可能在上下文退出之后才执行（异步 handler、`QueueHandler`、pytest 的延迟格式化），那时 contextvar 已复位、span 已结束，`request_id` 和 `trace_id` 就都成了空。所以在 `_emit` 里当场把关联 ID 和 span ID 并进字段，格式化只负责渲染。

这个问题是写测试时先暴露出来的：断言在 `with` 块之外读渲染结果，字段消失了。
