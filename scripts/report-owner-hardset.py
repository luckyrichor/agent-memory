"""Generate counts and handoff from immutable owner input and actual run evidence."""

import json
import math
import re
import shutil
import subprocess
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from agent_memory.evals.datasets import file_hash

ROOT = Path(".local/phase1/round3/owner-hardset")
OUT = Path("docs/reports/phase1-round3-owner-hardset-2026-10-21")
OLD = Path("docs/reports/phase1-round3-followup-2026-10-21")
HARD = ROOT / "synthetic-hard-v1-release"
FROZEN = Path(".local/phase1/round3/followup/chinese-queries-v1-ready")


def read(p):
    return json.loads(Path(p).read_text())


def lines(p):
    return [json.loads(s) for s in Path(p).read_text().splitlines()]


def write(p, x):
    Path(p).write_text(json.dumps(x, ensure_ascii=False, indent=2) + "\n")


OUT.mkdir(parents=True, exist_ok=True)
audit = read(ROOT / "native-audit-final/report.json")
assert audit["audit_count"] == 157 and audit["unchecked_count"] == 73
human = {r["item_id"]: r["label"] for r in lines(ROOT / "native-audit-final/adopted-labels.jsonl")}
refs = {
    r["item_id"]: r["label"]
    for r in lines(".local/phase1/chinese-expansion-v2/dulemon/references.jsonl")
}
items = {r["item_id"]: r for r in lines(".local/phase1/chinese-expansion-v2/dulemon/items.jsonl")}
pair = Path(".local/phase1/chinese-guide-v2-full-fallback-resume1/dulemon")
left = {r["item_id"]: r["label"] for r in lines(pair / "labels-deepseek-v4-pro-run1/labels.jsonl")}
right = {r["item_id"]: r["label"] for r in lines(pair / "labels-mimo-v2.6-flash-run1/labels.jsonl")}
joint = {k for k in left if left[k] == right[k] == "keep"}
human_positive = {k for k in human if human[k] == "keep"}
known_reject = {k for k in joint if k in human and human[k] != "keep"}
prospective = (joint - known_reject) | human_positive
population = Counter(refs.values())
confusion = Counter((refs[k], human[k]) for k in human)
gold = {
    "target": 1500,
    "confirmed_positive_points": len(human_positive),
    "gap": 1500 - len(human_positive),
    "human_labels": dict(Counter(human.values())),
    "reviewed_conversations": len({items[k]["conversation_id"] for k in human}),
    "positive_conversations": len({items[k]["conversation_id"] for k in human_positive}),
    "full_negative_conversation_count": None,
    "negative_conversation_ratio": None,
    "native_source_candidates": len(items),
    "native_source_conversations": len({x["conversation_id"] for x in items.values()}),
    "native_reference_counts": dict(population),
    "prospective_joint_keep": len(joint),
    "joint_known_owner_rejected": len(known_reject),
    "joint_owner_positive_overlap": len(joint & human_positive),
    "prospective_union": len(prospective),
    "prospective_gap": 1500 - len(prospective),
    "proposed_joint_audit_count": math.ceil(len(joint) * 0.1),
    "proposal_adopted": False,
    "confusion": [{"native": a, "human": b, "count": n} for (a, b), n in sorted(confusion.items())],
}
query = lines(FROZEN / "queries.jsonl")
query_sources = {
    cat: dict(Counter(q["source"] for q in query if q["category"] == cat))
    for cat in ("temporal-reasoning", "knowledge-update", "multi-session")
}
assert all(list(v) == ["customer-timeline-v1"] for v in query_sources.values())
hard = read(HARD / "manifest.json")
reproduction = read(ROOT / "synthetic-hard-v1-release-reproduction/manifest.json")
assert hard["files"] == reproduction["files"]
replacement = read(ROOT / "queries-hard-replacement-proposal/manifest.json")
assert replacement["frozen_queries_sha256"] == file_hash(FROZEN / "queries.jsonl")
links = {r["item_id"]: r for r in lines(HARD / "control-truth-private.jsonl")}
truth = {r["item_id"]: r for r in lines(HARD / "constructor-truth-private.jsonl")}
probe = read(ROOT / "controls-probe/run.json")
controls = []
for entry in probe["models"]:
    directory = ROOT / "controls-probe" / entry["model"]
    labels = {r["item_id"]: r["label"] for r in lines(directory / "labels.jsonl")}
    base = [k for k in labels if k in truth]
    groups = {}
    for mode in ("shuffle", "mask", "counterfactual"):
        sample = [k for k in labels if k in links and links[k]["control"] == mode]
        groups[mode] = {
            "n": len(sample),
            "constructor_expected_matches": sum(labels[k] == links[k]["expected"] for k in sample),
            "compared_with_base_label_changes": sum(
                labels[k] != labels[links[k]["base_item_id"]] for k in sample
            ),
        }
    ledger = read(directory / "ledger.json")
    controls.append(
        {
            **entry,
            "base_n": len(base),
            "base_expected_matches": sum(labels[k] == truth[k]["label"] for k in base),
            "controls": groups,
            "calls": sum(not x["replayed"] for x in ledger),
            "reported_tokens": sum((x.get("usage") or {}).get("total_tokens", 0) for x in ledger),
            "response_versions": sorted({x["response_model"] for x in ledger}),
            "prompt_sha256": ledger[0]["prompt_sha256"],
            "input_sha256": probe["items_sha256"],
            "ledger_sha256": file_hash(directory / "ledger.json"),
        }
    )
protected = read(".local/phase1/round3/followup/protected-hashes.json")
assert all(file_hash(Path(p)) == sha for p, sha in protected.items()), "frozen audit/ECD changed"
for p in (
    "docs/evals/metric-catalog.json",
    "docs/evals/human-review-policy-v1.json",
    "src/agent_memory/evals/metrics.py",
):
    assert subprocess.check_output(["git", "show", "d237974:" + p]) == Path(p).read_bytes()
assert (
    file_hash(Path(".local/phase1/timeline-v1/items.jsonl"))
    == "98b50d7f29c8955b7df1d5f0947773e39007c1ffb2bc88a9d7bcc9cc279ed1ae"
)
check = (ROOT / "check-final.log").read_text()
match = re.search(r"(\d+) passed in ([\d.]+)s", check)
assert (
    match
    and "All checks passed!" in check
    and "tenant_leaks=0" in check
    and "Success: no issues found" in check
)
validation = {
    "pytest_passed": int(match[1]),
    "seconds": float(match[2]),
    "ruff": "passed",
    "strict_mypy": "passed",
    "foundation": "8/8; tenant_leaks=0; deleted_memory_hits=0",
    "log_sha256": file_hash(ROOT / "check-final.log"),
}
shutil.copyfile(ROOT / "check-final.log", OUT / "validation.log")
policy = Path("docs/evals/phase1-round3-policy-v3.json")
pools = {}
for kind in ("public-chinese", "synthetic-timeline"):
    pool = read(OLD / (kind + "-judge-pool.json"))
    pool["candidates"] = [x for x in pool["candidates"] if x["model"] != "glm-5v-turbo"]
    pool.update(
        policy_path=str(policy),
        policy_sha256=file_hash(policy),
        preflight_pool_frozen=False,
        formal_execution_ready=False,
        missing_backups=max(0, 3 - len(pool["candidates"])),
        blocked_reason="stable backup shortage and owner calibration pending",
        withdrawn_model="TokenHub:glm-5v-turbo; historical preflight pass retained but pre-offline, not a stable backup",
    )
    write(OUT / (kind + "-judge-pool.json"), pool)
    pools[kind] = pool
catalogs = read(ROOT / "judge-discovery/catalogs.json")
failed = []
for p in sorted((ROOT / "judge-discovery").glob("*/progress.json")):
    r = read(p)
    failed.append(
        {
            "provider": r[0]["provider"],
            "model": r[0]["model"],
            "calls": len(r),
            "http_statuses": [x.get("http_status") for x in r],
            "preflight_pass": read(p.parent / (r[0]["model"] + "-summary.json"))["preflight_pass"],
            "evidence_sha256": file_hash(p),
        }
    )
selection = {
    "provenance": "owner message, not inferred from Agent labels",
    "old_agent_uncertain": 124,
    "old_agent_discard": 3,
    "old_agent_keep_random": 30,
    "random_sample": False,
}
assert (
    sum(selection[k] for k in ("old_agent_uncertain", "old_agent_discard", "old_agent_keep_random"))
    == audit["audit_count"]
)
report = {
    "date_beijing": str(datetime.now(ZoneInfo("Asia/Shanghai")).date()),
    "generated_at": datetime.now(UTC).isoformat(),
    "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
    "working_tree_modified": bool(
        subprocess.check_output(["git", "diff", "--", "src", "tests", "scripts", "docs/evals"])
    ),
    "phase1_accepted": False,
    "phase2_started": False,
    "owner_audit": {k: v for k, v in audit.items() if k != "reviewer"},
    "selection": selection,
    "real_chinese_gold": gold,
    "query_source_by_category": query_sources,
    "frozen_queries_sha256": file_hash(FROZEN / "queries.jsonl"),
    "hardset": hard,
    "hardset_reproduction_identical": True,
    "hardset_controls_actual": controls,
    "query_replacement_proposal": replacement,
    "judge_pools": pools,
    "judge_catalogs": {
        k: {"models": len(v["models"]), "http_status": v["http_status"], "queried_at": v["at"]}
        for k, v in catalogs.items()
    },
    "new_failed_candidates": failed,
    "new_live_model_calls": sum(x["calls"] for x in failed) + sum(x["calls"] for x in controls),
    "reported_tokens": sum(x["reported_tokens"] for x in controls),
    "error_response_usage_unknown": True,
    "ecd_review_unchanged": True,
    "protected_hashes": protected,
    "validation": validation,
    "inherited_retrieval_report": "docs/reports/phase1-round3-closeout-2026-10-21/report.json",
    "remaining": [
        "real Chinese gold below target; proposed recovery not approved",
        "stable judge backup shortage",
        "judge owner calibration pending",
        "hardset full independent model annotation and owner audit pending",
        "query replacement awaiting owner confirmation",
        "ECD deferred; no human labels inferred",
    ],
}
write(OUT / "report.json", report)
write(OUT / "owner-audit-summary.json", report["owner_audit"])
write(OUT / "hardset-manifest.json", hard)
write(OUT / "hardset-control-results.json", controls)
write(OUT / "query-replacement-proposal.json", replacement)
write(
    OUT / "judge-discovery-summary.json",
    {"catalogs": report["judge_catalogs"], "failed": failed, "checked_at": report["generated_at"]},
)
status = "流程验证，不作质量证据"
s = [
    "# agent-memory 阶段1：负责人回填与独立困难集交接",
    f"🤖 由 Codex 生成 · {report['date_beijing']} · 来源 agent-memory@{report['source_commit'][:7]} · 本地报告；未提交源码修改：{report['working_tree_modified']}",
    "",
    "**阶段1仍未验收，不进入阶段2。** 本报告更新当前状态，旧报告作为历史保留。全部规模、比例、边界和测试结果由 scripts/report-owner-hardset.py 读取工件生成。",
    "",
    "## 负责人回填与真实中文规模",
    f"附件 SHA256 `{audit['submitted_sha256']}`。原表ID、来源、候选、record_sha256与冻结审核集合均通过校验；旧Agent标签未作为人工输入。",
    f"已核对 {audit['audit_count']} / {audit['frozen_sample_count']}；未核对 {audit['unchecked_count']} 行保持空白。与未修正原生参照相符 {audit['matches']} 条：**{audit['matches']}/{audit['audit_count']} = {audit['frozen_reference_agreement']:.6%}**。",
    f"全表下界（空白全部不一致）{audit['matches']}/{audit['frozen_sample_count']} = {audit['full_sample_agreement_lower']:.6%}；上界（空白全部一致）{audit['matches'] + audit['unchecked_count']}/{audit['frozen_sample_count']} = {audit['full_sample_agreement_upper']:.6%}。这是确定性界限，不是置信区间。上界仍低于 {audit['threshold']:.0%}。",
    f"选择方式来自负责人说明：旧Agent uncertain {selection['old_agent_uncertain']}、discard {selection['old_agent_discard']}、keep随机 {selection['old_agent_keep_random']}。原冻结抽检表虽是随机抽样，本次已核对部分是按旧Agent标签选择，并非随机。疑难/不确定样本过采样，若这些样本更易与原生参照冲突，会把观察一致率拉低；但未知各层未核对结果，偏差符号和幅度不能严格确定。不能据此无偏外推全量原生标签的一致率，不能用Agent标签替代人工。",
    "",
    "| 原生参照 | 人工标签 | 条数 |",
    "|---|---|---:|",
]
s += [f"| {x['native']} | {x['human']} | {x['count']} |" for x in gold["confusion"]]
s += [
    "",
    f"按冻结规则拒绝直接采用整批原生金标。独立输出负责人确认的 {audit['audit_count']} 条标签及原始候选，其中应记 **{gold['confirmed_positive_points']}**、不应记 {gold['human_labels'].get('discard', 0)}；覆盖 {gold['reviewed_conversations']} 段会话，应记点分布于 {gold['positive_conversations']} 段。原文件/标签/切分不覆盖。",
    f"当前可确认的真实中文正记忆金标准 **{gold['confirmed_positive_points']}/{gold['target']}，缺 {gold['gap']}**。PerLTQA作者合成、时间线程序合成、ECD未核验负例和未审双模型标签均不补入该数。局部候选审核不能证明整段全无应记内容，完整负样本会话比例未验证；会话数量和负样本比例闸门仍未满足。",
    "",
    "### 补足方案（待负责人确认，未改冻结数据）",
    f"现有冻结双模型共同keep {gold['prospective_joint_keep']}，其中人工明确否定 {gold['joint_known_owner_rejected']}，与人工keep重叠 {gold['joint_owner_positive_overlap']}。先保留人工否定作为否决记录；若负责人批准该路径，去重并纠正后的潜在池为 {gold['prospective_union']}，距目标仍缺 {gold['prospective_gap']}，**尚非已接受金标**。",
    f"建议对共同keep池重新固定种子、独立随机盲抽 {gold['proposed_joint_audit_count']} 条（按冻结抽检比例向上取整），同时报告各来源/类别错误，不能复用本次按旧Agent标签挑选的样本来证明该池质量。通过后再由负责人确认新版本；不通过时仍只保留人工确认项。",
    "随后从未用且具有所需原生字段的DuLeMon对话中固定种子增量取样，沿用冻结双模型，记录去重清单、候选产出与全部对话分母；缺额用实际新增通过抽检的应记点补足，不能用预期产出宣称达标。对拟作负样本的完整会话另行确认，确保目标会话数与负样本比例；冻结模型失败则保留进度并请求更换授权。",
    "",
    "## 中文查询来源与解读",
    "| 题型 | 来源 | 条数 | 用途 |",
    "|---|---|---:|---|",
]
for cat, counts in query_sources.items():
    for origin, n in counts.items():
        s.append(f"| {cat} | {origin} | {n} | {status} |")
s += [
    f"这三类合计 {sum(sum(v.values()) for v in query_sources.values())} 条全部来自旧程序时间线。冻结查询总数 {len(query)}，SHA256 `{report['frozen_queries_sha256']}`。",
    "未来阶段2必须将这些题型单列为程序构造场景，不能将其高分解读为真实中文时间推理、更新或跨会话能力，也不能据此宣称真实用户质量提升。混合总分受来源占比影响，真实来源与合成来源必须分别报告；现阶段未执行阶段2评测。",
    "",
    "## 独立困难集与实跑对照",
    f"新集合 `{hard['name']}`（本地程序独立构造，未复制第三方语料；仓库未声明LICENSE，对外再分发许可未确定），种子 {hard['seed']}：{hard['conversations']} 段、{hard['candidates']} 候选、{hard['queries']} 查询，标签仅为构造真值（keep {hard['label_counts']['keep']} / discard {hard['label_counts']['discard']}），不是人工或全量双模型标签。",
    "在相同来源文档数/字符数分层中，正负候选严格平衡；来源与候选顺序独立打乱，ID为固定种子生成的不透明ID。加入他人偏好误归用户、临时活动误当长期偏好。来源文本带日期而非按列表位置推断先后。构造真值及对照关联只存独立私有文件，实际请求只含候选/主体/来源/匿名ID，不带truth/kind/control/expected字段。",
    f"对照输入 {hard['controls']} 条："
    + "、".join(f"{k} {v}" for k, v in hard["control_counts"].items())
    + f"。语义反事实仅改变一个来源轮次，构造预期翻转 {hard['expected_counterfactual_flips']} 条；遮蔽后预期为无证据discard。",
    f"同种子完整重建各数据文件校验和逐一一致，工件摘要 `{hard['artifact_digest']}`。这是可重现性，不是质量验收。",
    f"小样实跑沿用已有合成组合和冻结提示词，原始候选 {probe['sample_base']}、合计每模型 {probe['sample_total']} 输入；每类难例按来源长度等额选择。模型不知道对照标识。构造真值仅用于事后诊断：",
    "| 模型 | 原始符合预期 | 打乱符合预期 | 打乱后标签不变 | 遮蔽符合预期 | 反事实符合预期 | 反事实标签翻转 |",
    "|---|---:|---:|---:|---:|---:|---:|",
]
for row in controls:
    g = row["controls"]
    sh = g["shuffle"]
    ma = g["mask"]
    cf = g["counterfactual"]
    s.append(
        f"| {row['provider']} / {row['model']} | {row['base_expected_matches']}/{row['base_n']} | {sh['constructor_expected_matches']}/{sh['n']} | {sh['n'] - sh['compared_with_base_label_changes']}/{sh['n']} | {ma['constructor_expected_matches']}/{ma['n']} | {cf['constructor_expected_matches']}/{cf['n']} | {cf['compared_with_base_label_changes']}/{cf['n']} |"
    )
s += [
    "HY4的打乱不变率不是满分，不能只用对构造真值的符合率掩盖顺序敏感性。样本小、模板生成且同源变体混合调用，可能互相提示；也未证明模型在全量困难集上可靠。全量独立模型标注未做，人工未审核。仍统一标“流程验证，不作质量证据”。",
    f"人工抽检方案：四个候选层各随机抽取 {hard['owner_audit_proposed'] // 4} 条，总计 {hard['owner_audit_proposed']}（占基础候选 {hard['owner_audit_proposed'] / hard['candidates']:.0%}），仅来源和候选，human栏空白。先让负责人确认归属/临时性/时间证据和构造真值是否恰当；对照额外检查遮蔽与反事实是否只改变预定事实。负责人确认前不将构造真值视为金标，也不催办此前暂缓包。",
    f"替换提案已实际生成：按共同新会话选择每类 {replacement['replaced'] // len(query_sources)} 条，替换旧三类共 {replacement['replaced']} 条，其他 {replacement['unchanged_other_queries']} 条逐条保留，总数 {replacement['queries']}。新困难会话按自身固定切分，其他来源继承原切分，因此属于新版本提案，不能冒充与旧测试集同集比较。",
    "**待负责人确认**后才启用该新查询版本；冻结入口和旧文件仍保持。新版本也只作流程验证；经人工确认和独立评估后才能另议质量证据资格，不会因困难程度提高自动获得。",
    "",
    "## 裁判池与缺口",
    "GLM-5V旧完整预检的“通过”结论保留在历史中；因预下线，从当前稳定池撤下。新增v3策略与运行入口拒绝该模型，即便提供旧校准也不能绕过。不同表仍分别按实际标注/答题厂商排除，不更改门槛。",
    "| 对比表 | 主裁判（已有完整预检与实调） | 稳定备选 | 尚缺备选 |",
    "|---|---|---|---:|",
]
for kind, pool in pools.items():
    candidates = [x["provider"] + "/" + x["model"] for x in pool["candidates"]]
    s.append(
        f"| {kind} | {candidates[0]} | {', '.join(candidates[1:]) or '无'} | {pool['missing_backups']} |"
    )
s += [
    "公开池限已知冻结DuLeMon标注组合。PerLTQA原标注厂商未核实，不能自动套该池。主备均未完成人工裁判校准；两个池均未达到正式运行条件。",
    "| 渠道目录 | HTTP | 模型条目 | 查询日期 |",
    "|---|---:|---:|---|",
]
s += [f"| {k} | {v['http_status']} | {len(v['models'])} | {v['at']} |" for k, v in catalogs.items()]
s += ["| 本轮候选 | HTTP | 完整预检通过 |", "|---|---|---|"]
s += [
    f"| {v['provider']}/{v['model']} | {v['http_statuses']} | {v['preflight_pass']} |"
    for v in failed
]
s += [
    "目录可见不等于账号能调用；Ark NotFound不被推断为余额不足。TokenHub上述失败为额度/付费状态拒绝，未充值或开通后付费。首探失败不重复消耗做无意义完整预检。此前Step/视觉输出思考、角色模型控制未证实、MiMo等额度失败的记录保留，不把它们补入合格池。",
    "官方参数文档核对：GLM新系列及Kimi新系列存在不能关闭思考/温度固定的限制，不因目录出现就纳入；Kimi旧非思考温度也不是冻结温度。不放宽现有预检，不按余额凑数。",
    "[TokenHub思考控制](https://cloud.tencent.com/document/product/1823/131208)；[Kimi参数差异](https://cloud.tencent.com/document/product/1823/132232)；[GLM-5V下线公告](https://cloud.tencent.cn/announce/detail/2479)。",
    f"本轮实际模型请求 {report['new_live_model_calls']} 次（不含目录GET），成功调用上报token合计 {report['reported_tokens']}。错误返回未提供usage，其用量未知；没有余额查询、充值或后付费开通。预检与诊断都不等于负责人裁判校准。",
    "",
    "## 验证、保护与未完成",
    f"`bash scripts/check.sh`：pytest {validation['pytest_passed']} passed / {validation['seconds']}s；ruff、strict mypy通过；foundation {validation['foundation']}。证据 validation.log / report.json。",
    "已核对ECD审核表、原DuLeMon审核表、旧时间线、冻结中文查询及指标/验收定义的散列未变。原始对话、回填理由、控制请求响应只在服务器.local和负责人私有包；仓库只有脚本、方法、哈希及统计。",
    "LoCoMo和LongMemEval沿用前轮实跑证据，本轮未重跑、未冒称新结果。历史报告及源码版本见 inherited_retrieval_report。",
    "未完成：真实中文规模及完整会话负例覆盖；补足路径审批与独立抽检；困难集全量独立标注/人工核验；查询替换确认；稳定裁判备选补齐与人工校准；ECD负责人标注（继续暂缓）。阶段1未验收，未做阶段2。",
    "",
    "### 需要负责人决定",
    "请确认是否采用上述共同保留池抽检后补量的路径，以及是否在新版本查询中用困难集替换旧三类。当前只交付可审阅提案，未切换冻结数据。",
]
text = "\n\n".join(s) + "\n"
text = re.sub(r"(\|[^\n]*\|)\n\n(?=\|)", r"\1\n", text)
text = re.sub(r"\n{3,}", "\n\n", text)
(OUT / "delivery.md").write_text(text)
print(
    json.dumps(
        {
            "report": str(OUT / "delivery.md"),
            "gold": gold["confirmed_positive_points"],
            "gap": gold["gap"],
            "control_calls": sum(x["calls"] for x in controls),
            "tests": validation["pytest_passed"],
        },
        ensure_ascii=False,
    )
)
