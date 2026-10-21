# 阶段1第三轮补充：火山 Ark 裁判查询

> 当前状态以[第三轮收尾交接](../phase1-round3-closeout-2026-10-21/delivery.md)为准；本篇保留历史快照。

日期：2026-10-21（北京时间）；Codex；来源 agent-memory@1a55d7a（生成时工作区状态见JSON）。

本补充更新此前“只查腾讯云”的裁判范围；原交接报告的 ECD、审核和召回结论保持原状态。阶段1仍未验收，不进入阶段2。

模型列表 HTTP 200，共 137 个条目；列表包含已下线/无权限条目，不能视为全部可调用。

|模型|实测HTTP|五次完全一致|完整格式预检|可纳入候选|剩余额度|
|---|---:|---|---|---|---|
|glm-4-5-air-20250728|404|False|未继续|False|未知|
|qwen3-8b-20250429|404|False|未继续|False|未知|
|qwen3-32b-20250429|404|False|未继续|False|未知|
|qwen2-5-72b-20240919|404|False|未继续|False|未知|
|qwen3-0-6b-20250429|404|False|未继续|False|未知|
|qwen3-14b-20250429|404|False|未继续|False|未知|
|glm-5-2-260617|200|True|100/100|True|未知|
|glm-5-3-flash-260828|200|True|未继续|False|未知|

Ark GLM-5.2 完整预检 106 次，格式 100/100；正式裁判提示另外连续 5 次一致：True。使用temperature=0、thinking.type=disabled，返回模型为glm-5-2-260617，未观测到思考内容/思考token。该渠道与腾讯云GLM-5.2的免费包独立，不能把腾讯402推断成火山也没额度。
GLM-5.3-Flash虽返回200、样本一致且未显示思考token，官方仍写明始终思考、不支持禁用，不能仅凭请求成功判合格。Qwen/旧GLM的404只说明本次模型ID不存在或当前无权限，不据此判余额为零；没有可用Endpoint ID，未创建服务或开通计费。

合并上一轮腾讯证据后，严格预检合格的云渠道/模型组合共 3 个，涉及 2 个模型厂商：

- TokenHub / hy4-preview（Tencent）
- TokenHub / glm-5v-turbo（Zhipu）
- Ark / glm-5-2-260617（Zhipu）

同属GLM的不同版本/渠道不等于不同厂商；当前条件要求裁判与答题/标注厂商独立，并未要求裁判池内部每个模型来自不同厂商。腾讯候选沿用上轮有日期的证据，本轮未复测，正式冻结前还须重新确认。

## 剩余额度与下一步

额度管理接口实测 HTTP 400 / InvalidAuthorization；官方要求AK/SK签名，现有Ark推理API Key无法查询。正确查询参数为WithFreeUsage=true，返回InitialInferenceFreeUsage.Total与Consumed；这次请求在鉴权处失败，未获得额度，未改配置。
运行时/models、成功推理响应及响应头均未暴露数字余额。已有调用的usage只表示本次消耗，不能用来计算剩余额度。也未把TPM/RPM限流当可用余额。
因此目前补足的是可预检候选数量，尚不能按余额排序、指定额度最多主裁判或证明覆盖完整评测。预算沿用原报告及本JSON；不通过大量消耗探测余额，不充值、不启用后付费。
需要控制台各候选剩余额度截图/导出（带日期、单位，遮住密钥），或由用户在服务器配置具备只读额度查询权限的管理凭据；不要把AK/SK发到群里。
现有整表重判机制已实现，但运行CLI当前仅接TokenHub；跨云正式路由还未集成，本次仅做Ark可调用/预检与额度能力调查，不声称跨云自动切换已验收。人工230回填、裁判人工校准及原报告其他缺口仍未完成。

## 官方依据

- https://docs.volcengine.com/docs/ark/list-model-activations-api?lang=zh
- https://docs.volcengine.com/docs/ark/base-url-and-authentication?lang=en
- https://docs.volcengine.com/docs/ark/deep-thinking?lang=en
- https://docs.volcengine.com/docs/ark/chat-api?lang=en
