"""Generate a public aggregate Ark supplement from private actual-call artifacts."""

import argparse
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--input", type=Path, default=Path(".local/phase1/round3/ark"))
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()

    def read(name):
        return json.loads((a.input / name).read_text())

    catalog = read("catalog-private.json")["data"]
    discovery = read("discovery.json")
    access = read("access.json")
    repeat = read("judge-repeat.json")
    summary = read("preflight-glm-5-2-260617/glm-5-2-260617-summary.json")
    old = json.loads(Path("docs/reports/phase1-round3-2026-10-21/report.json").read_text())
    rows = []
    for row in access:
        model = row["model"]
        eligible = model == "glm-5-2-260617"
        qualified = (
            eligible
            and summary["preflight_pass"]
            and repeat["consistent_5"]
            and row["repeat_5_pass"]
        )
        rows.append(
            {
                "provider": "Ark",
                "model": model,
                "vendor": "Zhipu" if model.startswith("glm") else "Alibaba",
                "http_status": row["probes"][0].get("http_status"),
                "error_code": row["probes"][0].get("error_code"),
                "queried_at": row["queried_at"],
                "control_semantics_verified": eligible,
                "repeat_5_pass": row["repeat_5_pass"],
                "preflight": summary if eligible else None,
                "judge_prompt_consistent_5": repeat["consistent_5"] if eligible else None,
                "qualified_for_pool": qualified,
                "exclusion": (
                    "officially always-thinking, cannot disable; five identical answers/zero visible reasoning do not override documentation"
                    if model == "glm-5-3-flash-260828"
                    else "model ID missing or no access; endpoint availability not inferred"
                    if row["probes"][0].get("http_status") == 404
                    else None
                ),
                "remaining_tokens": None,
                "quota_sufficient": None,
                "usage_total_tokens_probe": sum(
                    x.get("usage", {}).get("total_tokens", 0) for x in row["probes"]
                ),
            }
        )
    prior = [
        {
            "provider": "TokenHub",
            "model": r["model"],
            "vendor": r["vendor"],
            "queried_at": r.get("queried_at"),
            "remaining_tokens": None,
        }
        for r in old["candidates"]
        if r["qualified_for_pool"]
    ]
    qualified = prior + [
        {k: r[k] for k in ("provider", "model", "vendor", "queried_at", "remaining_tokens")}
        for r in rows
        if r["qualified_for_pool"]
    ]
    date = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
    hashes = {
        str(x.relative_to(a.input)): hashlib.sha256(x.read_bytes()).hexdigest()
        for x in a.input.rglob("*")
        if x.is_file() and x.suffix in {".json", ".py"}
    }
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "date_beijing": date,
        "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "working_tree_modified": bool(subprocess.check_output(["git", "status", "--porcelain"])),
        "catalog_count": len(catalog),
        "catalog_http_status": discovery[0]["http_status"],
        "activation_quota_http_status": discovery[1]["http_status"],
        "activation_quota_error": discovery[1]["response"]["ResponseMetadata"]["Error"]["Code"],
        "quota_auth_requirement": "management AK/SK HMAC; runtime Bearer API key rejected; no quota evidence available",
        "quota_request_field_note": "WithFreeUsage=true sent; management authentication failed; neither quota nor model state inferred. No management credentials configured or service activated.",
        "candidates": rows,
        "qualified_candidates_combined": qualified,
        "qualified_endpoint_count": len(qualified),
        "qualified_distinct_vendor_count": len({r["vendor"] for r in qualified}),
        "all_candidates_revalidated_same_time": False,
        "numeric_remaining_quota_verified": False,
        "quota_ranked_pool_frozen": False,
        "primary_judge": None,
        "backups": [],
        "phase_gate_passed": False,
        "phase2_started": False,
        "existing_budget": old["budget"],
        "private_evidence_sha256": hashes,
        "sources": [
            "https://docs.volcengine.com/docs/ark/list-model-activations-api?lang=zh",
            "https://docs.volcengine.com/docs/ark/base-url-and-authentication?lang=en",
            "https://docs.volcengine.com/docs/ark/deep-thinking?lang=en",
            "https://docs.volcengine.com/docs/ark/chat-api?lang=en",
        ],
        "limitations": [
            "No remaining quota returned in runtime catalog, inference responses or headers; successful small calls do not prove full evaluation affordability.",
            "Prior Tencent results are archived evidence, not fresh retests this round.",
            "Vendor means model developer, not hosting cloud. Doubao/DeepSeek/MiMo remain excluded; frozen annotators unchanged.",
            "Current CLI run-judge-table.py only wires TokenHub transport; cross-cloud production dispatch is not yet integrated or claimed. Formal pool cannot freeze until actual quotas available.",
            "No owner audit/calibration performed; no annotation or phase2 evaluation run.",
        ],
    }
    lines = [
        "# 阶段1第三轮补充：火山 Ark 裁判查询",
        "",
        f"日期：{date}（北京时间）；Codex；来源 agent-memory@{report['source_commit'][:7]}（报告生成前含未提交修改，见JSON）。",
        "",
        "本补充更新此前“只查腾讯云”的裁判范围；原交接报告的 ECD、审核和召回结论保持原状态。阶段1仍未验收，不进入阶段2。",
        "",
        f"模型列表 HTTP {report['catalog_http_status']}，共 {report['catalog_count']} 个条目；列表包含已下线/无权限条目，不能视为全部可调用。",
        "",
        "|模型|实测HTTP|五次完全一致|完整格式预检|可纳入候选|剩余额度|",
        "|---|---:|---|---|---|---|",
    ]
    for r in rows:
        f = r["preflight"]
        lines.append(
            f"|{r['model']}|{r['http_status']}|{r['repeat_5_pass']}|{str(f['format_valid']) + '/' + str(f['format_n']) if f else '未继续'}|{r['qualified_for_pool']}|未知|"
        )
    lines += [
        "",
        f"Ark GLM-5.2 完整预检 {summary['calls']} 次，格式 {summary['format_valid']}/{summary['format_n']}；正式裁判提示另外连续 {len(repeat['records'])} 次一致：{repeat['consistent_5']}。使用temperature=0、thinking.type=disabled，返回模型为glm-5-2-260617，未观测到思考内容/思考token。该渠道与腾讯云GLM-5.2的免费包独立，不能把腾讯402推断成火山也没额度。",
        "GLM-5.3-Flash虽返回200、样本一致且未显示思考token，官方仍写明始终思考、不支持禁用，不能仅凭请求成功判合格。Qwen/旧GLM的404只说明本次模型ID不存在或当前无权限，不据此判余额为零；没有可用Endpoint ID，未创建服务或开通计费。",
        "",
        f"合并上一轮腾讯证据后，严格预检合格的云渠道/模型组合共 {report['qualified_endpoint_count']} 个，涉及 {report['qualified_distinct_vendor_count']} 个模型厂商：",
        "",
    ]
    for r in qualified:
        lines.append(f"- {r['provider']} / {r['model']}（{r['vendor']}）")
    lines += [
        "",
        "同属GLM的不同版本/渠道不等于不同厂商；当前条件要求裁判与答题/标注厂商独立，并未要求裁判池内部每个模型来自不同厂商。腾讯候选沿用上轮有日期的证据，本轮未复测，正式冻结前还须重新确认。",
        "",
        "## 剩余额度与下一步",
        "",
        f"额度管理接口实测 HTTP {report['activation_quota_http_status']} / {report['activation_quota_error']}；官方要求AK/SK签名，现有Ark推理API Key无法查询。正确查询参数为WithFreeUsage=true，返回InitialInferenceFreeUsage.Total与Consumed；这次请求在鉴权处失败，未获得额度，未改配置。",
        "运行时/models、成功推理响应及响应头均未暴露数字余额。已有调用的usage只表示本次消耗，不能用来计算剩余额度。也未把TPM/RPM限流当可用余额。",
        "因此目前补足的是可预检候选数量，尚不能按余额排序、指定额度最多主裁判或证明覆盖完整评测。预算沿用原报告及本JSON；不通过大量消耗探测余额，不充值、不启用后付费。",
        "需要控制台各候选剩余额度截图/导出（带日期、单位，遮住密钥），或由用户在服务器配置具备只读额度查询权限的管理凭据；不要把AK/SK发到群里。",
        "现有整表重判机制已实现，但运行CLI当前仅接TokenHub；跨云正式路由还未集成，本次仅做Ark可调用/预检与额度能力调查，不声称跨云自动切换已验收。人工230回填、裁判人工校准及原报告其他缺口仍未完成。",
        "",
        "## 官方依据",
        "",
    ]
    lines += ["- " + url for url in report["sources"]]
    a.output.mkdir(parents=True, exist_ok=False)
    (a.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    (a.output / "delivery.md").write_text("\n".join(lines) + "\n")
    print(
        json.dumps(
            {
                "report": str(a.output),
                "qualified_endpoint_count": len(qualified),
                "quota_verified": False,
            }
        )
    )


if __name__ == "__main__":
    main()
