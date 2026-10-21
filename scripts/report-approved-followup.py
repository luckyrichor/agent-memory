"""Script-generated handoff for approved sampling, query activation and one-backup rule."""

import difflib
import importlib.metadata
import json
import platform
import re
import shutil
import subprocess
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from agent_memory.evals.datasets import file_hash
from agent_memory.evals.judge_pool import judge_budget

ROOT = Path(".local/phase1/round3/approved-followup")
OUT = Path("docs/reports/phase1-round3-approved-followup-2026-10-21")
PREVIOUS = Path("docs/reports/phase1-round3-owner-hardset-2026-10-21")
PLAN = Path("docs/plans/2026-10-21-agent-memory-interview-plan-v2.md")
OLD_PLAN = Path("docs/plans/2026-10-21-agent-memory-interview-plan.md")
POLICY = Path("docs/evals/phase1-round3-policy-v4.json")


def read(p):
    return json.loads(Path(p).read_text())


def records(p):
    return [json.loads(s) for s in Path(p).read_text().splitlines()]


def write(p, v):
    Path(p).write_text(json.dumps(v, ensure_ascii=False, indent=2) + "\n")


OUT.mkdir(parents=True, exist_ok=True)
patch = "".join(
    difflib.unified_diff(
        OLD_PLAN.read_text().splitlines(True),
        PLAN.read_text().splitlines(True),
        fromfile=str(OLD_PLAN),
        tofile=str(PLAN),
    )
)
(OUT / "plan-diff.patch").write_text(patch)
assert file_hash(PLAN) == file_hash(Path(".local/agent-memory-plan-20261021-owner-revision.md"))
audit = read(ROOT / "joint-audit-72-v1/manifest.json")
assert audit["sample"] == 72 and audit["previous_review_overlap"] == 0
current = read("docs/evals/chinese-query-current.json")
for d in current["files"].values():
    assert file_hash(Path(d["path"])) == d["sha256"]
queries = records(current["files"]["queries"]["path"])
old_root = Path(".local/phase1/round3/followup/chinese-queries-v1-ready")
old_queries = records(old_root / "queries.jsonl")
flow = set(current["flow_only_categories"])
old_kept = {q["question_id"]: q for q in old_queries if q["category"] not in flow}
new_kept = {q["question_id"]: q for q in queries if q["category"] not in flow}
assert old_kept == new_kept
assert all(
    q["source"] == "synthetic-hard-v1" and q["reference_status"] == "流程验证，不作质量证据"
    for q in queries
    if q["category"] in flow
)
protected = read(".local/phase1/round3/followup/protected-hashes.json")
assert all(file_hash(Path(p)) == sha for p, sha in protected.items())
assert (
    file_hash(old_root / "queries.jsonl") == read(PREVIOUS / "report.json")["frozen_queries_sha256"]
)
for path in (
    "docs/evals/metric-catalog.json",
    "docs/evals/human-review-policy-v1.json",
    "src/agent_memory/evals/metrics.py",
):
    assert subprocess.check_output(["git", "show", "72e269b:" + path]) == Path(path).read_bytes()
policy = read(POLICY)
pools = {}
for kind in ("public-chinese", "synthetic-timeline"):
    pool = read(PREVIOUS / (kind + "-judge-pool.json"))
    pool.update(
        policy_path=str(POLICY),
        policy_sha256=file_hash(POLICY),
        minimum_backups=policy["judge_minimum_backups"],
        missing_backups=max(0, 1 + policy["judge_minimum_backups"] - len(pool["candidates"])),
        preflight_pool_frozen=len(pool["candidates"]) >= 1 + policy["judge_minimum_backups"],
        formal_execution_ready=False,
    )
    pool["blocked_reason"] = (
        "owner calibration pending"
        if pool["preflight_pool_frozen"]
        else "one stable backup missing; owner calibration pending"
    )
    pool["workload_estimate"] = judge_budget(len(queries), 4, 3)
    write(OUT / (kind + "-judge-pool.json"), pool)
    pools[kind] = pool
failures = []
for p in sorted((ROOT / "judge-probes").glob("*/progress.json")):
    rows = read(p)
    failures.append(
        {
            "model": rows[0]["model"],
            "provider": rows[0]["provider"],
            "http_status": [r.get("http_status") for r in rows],
            "calls": len(rows),
            "preflight_pass": read(p.parent / (rows[0]["model"] + "-summary.json"))[
                "preflight_pass"
            ],
            "checked_at": read(p.parent / "report.json")["created_at"],
            "evidence_sha256": file_hash(p),
        }
    )
check = (ROOT / "check.log").read_text()
test = re.search(r"(\d+) passed in ([\d.]+)s", check)
assert (
    test
    and "All checks passed!" in check
    and "Success: no issues found" in check
    and "tenant_leaks=0" in check
)
validation = {
    "pytest": int(test[1]),
    "seconds": float(test[2]),
    "ruff": "pass",
    "strict_mypy": "pass",
    "foundation": "total=8 passed=8 failed=0 tenant_leaks=0 deleted_memory_hits=0",
    "log_sha256": file_hash(ROOT / "check.log"),
}
shutil.copyfile(ROOT / "check.log", OUT / "validation.log")
prior = read(PREVIOUS / "report.json")
gold = prior["real_chinese_gold"]["confirmed_positive_points"]
report = {
    "created_at": datetime.now(UTC).isoformat(),
    "date_beijing": str(datetime.now(ZoneInfo("Asia/Shanghai")).date()),
    "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
    "source_modified": bool(
        subprocess.check_output(["git", "diff", "--", "src", "tests", "scripts", "docs/evals"])
    ),
    "phase1_accepted": False,
    "phase2_started": False,
    "plan": {
        "new": str(PLAN),
        "sha256": file_hash(PLAN),
        "old": str(OLD_PLAN),
        "old_sha256": file_hash(OLD_PLAN),
        "diff_hunks": sum(x.startswith("@@") for x in patch.splitlines()),
        "original_author_preserved": True,
    },
    "plan_conflicts": [
        "section7 old backup row still requires two; current explicit owner instruction and selection bullet require one",
        "section7 heading/table still TokenHub-only but selection rule allows Ark; execute per-table vendor rule",
        "section11 generic owner95% retained; this independent audit uses specifically approved at most3 errors in72",
    ],
    "joint_audit": audit,
    "human_return_received": False,
    "audit_errors": None,
    "audit_passed": None,
    "error_rate_ci95": None,
    "gold": {
        "confirmed": gold,
        "minimum": policy["real_chinese_minimum_points"],
        "target": policy["real_chinese_target_points"],
        "minimum_gap": policy["real_chinese_minimum_points"] - gold,
        "target_gap": policy["real_chinese_target_points"] - gold,
        "scale_ci": None,
        "scale_ci_reason": "confirmed selected subset is a census of these adopted points, not a random estimate of full data; no new random-audit return yet",
    },
    "queries": {
        "version": current["version"],
        "active": True,
        "count": len(queries),
        "replaced_flow_only": sum(q["category"] in flow for q in queries),
        "unchanged_others": len(old_kept),
        "categories": dict(Counter(q["category"] for q in queries)),
        "by_source": dict(Counter(q["source"] for q in queries)),
        "registry": current,
        "source_split_sha256": file_hash(old_root / "split.json"),
        "old_queries_sha256": file_hash(old_root / "queries.jsonl"),
        "new_corpus_sha256": file_hash(ROOT / "chinese-queries-v2/corpus.jsonl"),
        "conversations": len(records(ROOT / "chinese-queries-v2/corpus.jsonl")),
        "same_set_comparison_allowed": False,
        "hardset_owner_audit_deferred": True,
    },
    "judge_pools": pools,
    "judge_new_failures": failures,
    "model_calls": sum(x["calls"] for x in failures),
    "reported_tokens": 0,
    "error_usage_unknown": True,
    "protected_hashes": protected,
    "incremental_sampling_started": False,
    "complete_negative_conversations_confirmed": False,
    "format_approved": True,
    "format_preview_superseded": True,
    "private_audit_delivery_message": "om_x100b62bf9b49b0b0ce4f2a5a84ed1d3",
    "environment": {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "httpx": importlib.metadata.version("httpx"),
        "pydantic": importlib.metadata.version("pydantic"),
    },
    "validation": validation,
    "commands": {
        "audit": "uv run python scripts/prepare-approved-joint-audit.py --items .local/phase1/chinese-expansion-v2/dulemon/items.jsonl --left .local/phase1/chinese-guide-v2-full-fallback-resume1/dulemon/labels-deepseek-v4-pro-run1/labels.jsonl --right .local/phase1/chinese-guide-v2-full-fallback-resume1/dulemon/labels-mimo-v2.6-flash-run1/labels.jsonl --prior-human .local/phase1/round3/owner-hardset/native-audit-final/adopted-labels.jsonl --output .local/reproduction-joint72",
        "queries": "uv run python scripts/materialize-current-chinese-queries.py --output .local/reproduction-queries-v2.jsonl",
        "finalize": "uv run python scripts/finalize-approved-joint-audit.py --pack .local/phase1/round3/approved-followup/joint-audit-72-v1 --submitted OWNER_RETURN.csv --output .local/joint72-owner-result --reviewer OWNER_ID",
        "checks": "bash scripts/check.sh",
    },
}
write(OUT / "report.json", report)
write(OUT / "joint-audit-manifest.json", audit)
write(OUT / "query-activation.json", report["queries"])
write(OUT / "judge-probes.json", failures)
s = [
    "# agent-memory 阶段1：获批补量路径与查询版本启用",
    f"🤖 由 Codex 生成 · {report['date_beijing']} · agent-memory@{report['source_commit'][:7]} · 未提交源码修改：{report['source_modified']}",
    "**阶段1仍未验收，不进入阶段2。** 本报告由 scripts/report-approved-followup.py 生成；审核数据仅服务器本地和负责人私聊，仓库不含对话本体。",
    "## 新版方案与差异",
    f"已完整重读最新版原件并另存 `{PLAN}`，保留 @sh6_apple 原署名。新文件 SHA256 `{file_hash(PLAN)}`；旧文件保留，SHA256 `{file_hash(OLD_PLAN)}`；逐行差异见 plan-diff.patch。",
    f"新增：真实中文金标过关下限 {policy['real_chinese_minimum_points']}、目标 {policy['real_chinese_target_points']}；明确独立盲抽 {audit['sample']} 且最多错误 {audit['maximum_errors']}；困难查询替换获批；裁判至少 {policy['judge_minimum_backups']} 个合格备选。",
    "文件内部尚有旧文：第7节角色表仍写至少两个备选，标题/表格仍只写腾讯渠道；按本轮明确指令及新版选择规则执行至少一个备选、允许Ark、按每张数据表排除厂商。原件不擅改。通用负责人95%门槛仍保留，本次特批72条按最多3个错误执行，不改其他审核阈值。",
    "## 独立盲抽与交付",
    f"冻结共同保留 {audit['joint_keep']}，扣除人工否定 {audit['owner_rejected_removed']} 后为 {audit['remaining_pool']}。其中已被负责人确认的 {audit['prior_reviewed_in_remaining_pool']} 条不重复送审；未审核总体 {audit['eligible_unreviewed_pool']} 中，以新种子 {audit['seed']} 简单随机不放回抽 {audit['sample']} 条，再打乱展示顺序。与此前人工核对项重叠 {audit['previous_review_overlap']}；覆盖 {audit['conversations']} 段对话。不是从全部剩余池不加区分抽样；已确认项属于已知层，未知层单独随机抽检。",
    "格式最初提供虚构预览，负责人否决后明确指定沿用原八列并授权直接发送。现已严格采用：`item_id, conversation_id, subject, candidate, source, record_sha256, human_label, human_reason`。item_id是不透明随机编号，映射只留本地；source保持原JSON逐轮结构，未摘要、未拼成文本；人工两栏空白，模型标签/参照/类别提示不进入表。",
    f"真实表已私聊交付负责人，CSV SHA256 `{audit['files']['audit-blind.csv']}`。已用接收器验证空白行、记录哈希、来源与候选逐字不变；完整JSONL和匿名映射本地保留。未向群发送真实表，先前虚构预览不是审核数据。",
    "| 原始来源 | 条数 |",
    "|---|---:|",
]
s += [f"| {key} | {n} |" for key, n in sorted(audit["source_counts"].items())]
s += ["### 描述性类别分布", "| 描述性类别 | 条数 |", "|---|---:|"]
s += [f"| {key} | {n} |" for key, n in sorted(audit["topic_counts"].items())]
s += [
    "类别只按候选文本的固定正则、首条命中互斥归类；用于分布描述，不是人工/模型金标，不向审核者显示。原始来源train是数据包来源名，不代表重新划分本项目开发/测试集。",
    "### 人工回填、置信区间与后续门槛",
    f"当前未收到本次 {audit['sample']} 条的人工回填，错误数、通过状态、错误率及置信区间均为空。回填必须完整；discard或uncertain均不视为正确keep，最多 {audit['maximum_errors']} 条非keep才通过。不得用模型答案、构造规则或此前旧标签充人工。",
    "回填后报告未知层有限总体的95%双侧等尾超几何精确区间，再结合已确认层加权到剩余池；同时给出观察错误率。分子/分母和先前已确认层单独报告。通用实验指标仍沿用原会话级bootstrap；本次有限总体审核区间方法明确单列，不改变指标公式。区间上界可能高于5%，这是不确定性，不擅自把“上界≤5%”加为新门槛，也不把“≤3错通过”说成统计证明真实错误率必≤5%。",
    f"当前已确认应记仍为 {gold}，离新下限 {report['gold']['minimum']} 缺 {report['gold']['minimum_gap']}，离目标 {report['gold']['target']} 缺 {report['gold']['target_gap']}。这是已确认子集的确切数量，不是对全量的随机估计，不能给这个固定数编造置信区间。新池尚未通过，未计入金标；抽检通过后才报告其实际采用规模及抽检区间。",
    "增量DuLeMon取样尚未开始：按批准顺序，先等抽检通过，再从未使用且有所需字段的对话固定种子补量，继承冻结切分、完整记录已用清单和所有对话分母。只计实际新增且通过抽检的记忆点；标注模型保持deepseek-v4-pro与mimo-v2.6-flash，失败保留进度并请求负责人确认更换。整段负样本会话尚未人工确认，不能由若干候选discard推定完整负例；会话数与负样本比例闸门仍待满足。",
    "## 新版中文查询已启用",
    f"当前版本 `{current['version']}`：{len(queries)} 查询、{report['queries']['conversations']} 段来源；替换三类共 {report['queries']['replaced_flow_only']}，其他 {report['queries']['unchanged_others']} 逐题核验保持。注册入口 `docs/evals/chinese-query-current.json`，数据SHA256 `{current['files']['queries']['sha256']}`，可生成普通评测入口可读的corpus.jsonl。",
    "| 题型 | 数量 | 口径 |",
    "|---|---:|---|",
]
s += [
    f"| {cat} | {count} | {'流程验证，不作质量证据；阶段2单列' if cat in flow else '按原来源口径解释，不外推真人质量'} |"
    for cat, count in sorted(report["queries"]["categories"].items())
]
s += [
    f"旧查询文件与旧切分原样保留。新数据集SHA与旧版不同，新旧不可同集比较；新困难会话使用该集合原有固定切分，其他来源继承原切分。新corpus SHA256 `{report['queries']['new_corpus_sha256']}`。",
    "已在评分入口实现flow_only_by_type隔离：三类只进入流程分项，不进入质量总指标或配对质量差异；同集比较检查仍保留数据集哈希。这里只执行夹具测试验证隔离机制，未运行阶段2质量评测。困难集人工抽检继续暂缓，不催办。",
    "## 裁判：至少一个备选",
    "| 数据表 | 主裁判 | 预检通过备选 | 尚缺 | 正式运行 |",
    "|---|---|---|---:|---|",
]
for kind, pool in pools.items():
    names = [x["provider"] + "/" + x["model"] for x in pool["candidates"]]
    s.append(
        f"| {kind} | {names[0]} | {', '.join(names[1:]) or '无'} | {pool['missing_backups']} | {'待人工校准' if pool['preflight_pool_frozen'] else '备选不足，且待人工校准'} |"
    )
s += [
    "公开表满足的是当前预检数量要求，主备均未完成人工校准，不宣称正式评分已就绪。合成表因Tencent也是标注厂商不能拿HY4当备选；GLM-5V预下线不回填稳定池。主备最低数量已同时接入策略文件、池加载器和运行入口，正式池不足会拒绝运行。",
    "| 本轮补查 | 日期 | HTTP | 完整预检通过 |",
    "|---|---|---|---|",
]
s += [
    f"| {x['provider']}/{x['model']} | {x['checked_at']} | {x['http_status']} | {x['preflight_pass']} |"
    for x in failures
]
s += [
    f"本轮额外调用 {report['model_calls']} 次，均在首探失败后停止，错误响应没有usage，不能写成实际消耗为零。未查余额、未充值、未开后付费。未找到合成表合格备选；此前不能关闭思考、采样控制未证实或额度失败的候选不为凑数纳入。已有主备完整预检/实调证据保留引用前轮文件，未冒称本轮重跑。",
    "## 验证与未完成项",
    f"完整四门：pytest {validation['pytest']} passed / {validation['seconds']}s；ruff、strict mypy通过；foundation {validation['foundation']}。环境与原始验证日志见report.json、validation.log。",
    "保护核验：ECD原审核表、原生DuLeMon审核表、旧查询、原指标定义和通用审核阈值哈希保持。新政策是负责人批准的单独版本，旧政策作为历史保留。",
    "未完成：本次独立人工审核及采纳池、增量补量、整段负样本确认、合成表裁判备选、裁判人工校准。ECD和困难集人工审核仍暂缓；未代签。阶段1尚未验收，不进入阶段2。",
    "## 复现与回填命令",
]
for name, command in report["commands"].items():
    s += [f"### {name}", f"```bash\n{command}\n```"]
text = "\n\n".join(s) + "\n"
text = re.sub(r"(\|[^\n]*\|)\n\n(?=\|)", r"\1\n", text)
(OUT / "delivery.md").write_text(text)
print(
    json.dumps(
        {
            "report": str(OUT / "delivery.md"),
            "sample": audit["sample"],
            "query_version": current["version"],
            "tests": validation["pytest"],
        }
    )
)
