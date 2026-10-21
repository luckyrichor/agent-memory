"""Generate audit failure, confirmed subset and rejected-filter diagnostics from artifacts."""

import json, re, shutil, subprocess
from datetime import datetime, UTC
from pathlib import Path
from zoneinfo import ZoneInfo
from agent_memory.evals.datasets import file_hash

ROOT = Path(".local/phase1/round3/verbatim-filter")
RUN = ROOT / "run-final"
OUT = Path("docs/reports/phase1-round3-verbatim-filter-2026-10-21")


def read(p):
    return json.loads(Path(p).read_text())


def write(p, x):
    Path(p).write_text(json.dumps(x, ensure_ascii=False, indent=2) + "\n")


OUT.mkdir(parents=True, exist_ok=True)
r = read(RUN / "summary.json")
for path, sha in r["input_hashes"].items():
    assert file_hash(Path(path)) == sha
protected = read(".local/phase1/round3/followup/protected-hashes.json")
assert all(file_hash(Path(p)) == h for p, h in protected.items())
for p in (
    "docs/evals/metric-catalog.json",
    "docs/evals/human-review-policy-v1.json",
    "src/agent_memory/evals/metrics.py",
    "docs/evals/chinese-query-current.json",
):
    assert subprocess.check_output(["git", "show", "a5de38a:" + p]) == Path(p).read_bytes()
log = (ROOT / "check.log").read_text()
tests = re.search(r"(\d+) passed in ([\d.]+)s", log)
assert (
    tests
    and "All checks passed!" in log
    and "Success: no issues found" in log
    and "tenant_leaks=0" in log
)
validation = {
    "pytest": int(tests[1]),
    "seconds": float(tests[2]),
    "ruff": "pass",
    "strict_mypy": "pass",
    "foundation": "8/8; tenant_leaks=0; deleted_memory_hits=0",
    "log_sha256": file_hash(ROOT / "check.log"),
}
report = {
    "additional_rejected_relation_trial": read(ROOT / "run-v3-probe/summary.json"),
    **r,
    "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
    "source_modified": bool(
        subprocess.check_output(["git", "diff", "--", "src", "tests", "scripts", "docs/evals"])
    ),
    "date_beijing": str(datetime.now(ZoneInfo("Asia/Shanghai")).date()),
    "generated_at": datetime.now(UTC).isoformat(),
    "validation": validation,
    "protected_hashes": protected,
    "implementation_status": "experimental post-filter rejected as too destructive; not an approved production filter",
    "unfinished": [
        "usable filter with adequate correct-item retention",
        "independent fresh audit72 after a suitable filter",
        "filter/changed-candidate approval",
        "incremental annotation",
        "whole-negative-conversation verification",
        "synthetic judge stable backup and owner calibration",
    ],
    "reproduction": "uv run python scripts/analyze-owner72-verbatim.py --output .local/reproduction-owner72-verbatim; bash scripts/check.sh; uv run python scripts/report-verbatim-filter.py",
    "scope": "agent-memory phase1 only; no model calls or raw public-data publication",
}
write(OUT / "report.json", report)
write(OUT / "audit-and-filter-summary.json", r)
shutil.copyfile(ROOT / "check.log", OUT / "validation.log")
shutil.copyfile("docs/evals/verbatim-filter-v1.md", OUT / "filter-proposal.md")
precision = r["sample_precision_cluster_ci95"]
lo, hi = precision["ci95"]
plo, phi = r["remaining_pool_precision_exact_ci95"]
recall = r["offline_error_recall"]
harm = r["offline_correct_harm"]
s = [
    "# agent-memory 阶段1：共同保留池抽检失败与逐字证据过滤实验",
    f"🤖 由 Codex 生成 · {report['date_beijing']} · 来源 agent-memory@{report['source_commit'][:7]} · 未提交源码修改：{report['source_modified']}",
    "**阶段1未验收，不进入阶段2。共同保留池未通过，过滤原型也未获通过；没有新的盲审表或增量标注。** 本报告全部数字由 scripts/report-verbatim-filter.py 从人工原附件、冻结映射、过滤结果和验证日志生成。",
    "## 真实回填与原池结论",
    f"附件 `dulemon72-final.csv` SHA256 `{r['input_return_sha256']}`，通过原盲表ID、候选、完整source、记录哈希和完整回填校验。负责人授权的统一keep理由被原样保留；没有把Agent标签当人工结果。",
    f"本次 {r['audit_sample']} 条中keep {r['new_keep']}、discard {r['new_discard']}。错误 {r['new_discard']} > 获批上限 {r['maximum_errors']}，**抽检未通过**。样本精度 {r['new_keep']}/{r['audit_sample']} = {precision['value']:.2%}；按冻结通用比例口径、来源会话聚类bootstrap的95% CI为 **{lo:.2%}–{hi:.2%}**，重采样会话数 {precision['n']}。",
    f"当初随机抽的是未审核层，另有既往已确认层：按此前冻结的有限总体精确区间算法，剩余池错误条数95% CI为 {r['remaining_pool_error_count_exact_ci95']}，结合已确认项后的池精度95% CI为 **{plo:.2%}–{phi:.2%}**。这是总体质量不确定性的区间，不是金标数量；不改变“最多错误{r['maximum_errors']}条”的验收条件。",
    "不能整体采用共同保留池。两个模型共同keep既不是人工确认，也不是通过本次抽检；本次人工keep仅对应这些具体候选，不向未审核项外推。原冻结模型标签/切分保留，整体采纳资格撤回。",
    "## 人工确认真实中文规模",
    f"此前人工应记 {r['previous_gold']} + 本次 {r['new_keep']}，按原item_id还原后重叠 {r['overlap']}，合计 **{r['confirmed_positive_points']} 条**，分布于 {r['confirmed_positive_conversations']} 段对话；累计人工核对 {r['human_checked_items']} 项。",
    f"距阶段1保底 {r['minimum']} 尚缺 **{r['minimum_gap']}**，距目标 {r['target']} 尚缺 {r['target_gap']}。这些人工确认的确切数量无需编造抽样置信区间；置信区间对应上面的池精度。注册信息 `docs/evals/human-confirmed-current.json`，原始候选、原人工理由及标签只存私有目录。",
    "过滤器将人工keep降级属于过滤器误伤，不会据此撤销负责人标签；该人工确认子集保持独立。PerLTQA作者构造、时间线合成、未核验ECD、未审共同keep均未计入真实中文正例规模。整段负样本会话仍需独立确认。",
    "## 错误分类",
    "| 互斥主因（按负责人理由归类） | 条数 |",
    "|---|---:|",
    *[f"| {kind} | {n} |" for kind, n in sorted(r["primary_error_types"].items())],
    "“无依据细节/推断”包括程度放大、从当下行为推长期偏好、补全完整姓名/场景/诊断、推定具体月份与刚刚发生等；“助手归属”指理由明确指出助手称呼或先提出事实。分类依据与逐条审计结果存私有文件，不把源码规则分类冒充额外人工标注。",
    "### 非互斥补充标签",
    "| 标签 | 条数 |",
    "|---|---:|",
    *[f"| {kind} | {n} |" for kind, n in sorted(r["secondary_error_tags_overlapping"].items())],
    "两个归属错误也包含未被用户原话支持的细节，因此补充标签会重叠，不能相加当作错误总数。公开报告只写类型；含原文和负责人的具体理由只给负责人私有包。",
    "## 逐字核验方案与本轮原型",
    "规范见 filter-proposal.md。逐项检查主体、关系、实体、程度、频率、数量、时间、诊断确定性；每一项都要记录用户原句、角色和source_id。候选里有用户原话未出现的具体细节，一律不支持，完整候选降为uncertain，不偷偷删掉修饰后称原候选正确。",
    "只查原始role=user轮次；助手先提、第三人、问句、假设和否定不当成本人肯定事实。“对啊/嗯嗯”不能补出用户本人未复述的完整姓名、诊断或特定时间。一次行为不能自动升级为长期喜欢；日期必须绑定同一个事件，不从订婚日期推结婚日期。",
    "实现保留严格顺序对齐原型，并试验按具体片段覆盖：仅做闭合语法/亲属称谓归一化，细节词需要连续原话，按陈述子句限制主体、谓词和事件；不能把不同子句的日期与事件拼接。每条私有判定记录原话与片段。它仍不是完整语义蕴含器，无法可靠处理中性意译和指代。",
    "| 开发集离线指标 | 分子/分母 | 值 |",
    "|---|---:|---:|",
    f"| 已知错误拦截召回 | {recall['numerator']}/{recall['denominator']} | {recall['value']:.2%} |",
    f"| 人工正确项被降级的误伤率 | {harm['numerator']}/{harm['denominator']} | {harm['value']:.2%} |",
    f"| 人工正确项保留数 | {r['offline_correct_retained']}/{r['new_keep']} | {r['offline_correct_retained'] / r['new_keep']:.2%} |",
    "**当前过滤器不合格，未声称离线验证通过。** 高错误召回不能掩盖误伤。人工标签保持，失败反映过滤器的处理能力不足，不把人工keep擅自改成discard。没有负责人批准的误伤阈值，也没有自行新增一条验收标准来凑“通过”。",
    f"本次 {r['audit_sample']} 条用于开发/调试，不能再作为该过滤器的独立通过证据。没有拿本次训练式调试的高召回当未来真实召回；这个小集合也不能证明泛化。",
    "### 追加探索（未采纳）",
    f"还试验过有限的亲属存在表达、爱好同义和省略主语处理：错误拦截 {report['additional_rejected_relation_trial']['offline_error_recall']['numerator']}/{report['additional_rejected_relation_trial']['offline_error_recall']['denominator']}，正确项误伤 {report['additional_rejected_relation_trial']['offline_correct_harm']['numerator']}/{report['additional_rejected_relation_trial']['offline_correct_harm']['denominator']}，未审支持项 {report['additional_rejected_relation_trial']['fresh_unreviewed_supported']}，仍不足 {report['additional_rejected_relation_trial']['fresh_sample_target']}。该探索涉及额外关系解释，既未解决误伤，也未获得可独立审核的足够池，因此未采纳；源码快照与结果留存本地。当前主线保留保守诊断版本，不启用任何版本。",
    "## 新独立盲审为什么未生成",
    f"原共同keep {r['global_joint_keep']}；累计已被人工否定 {r['owner_rejected_in_joint']} 后剩 {r['remaining_after_known_rejects']}。原型支持 {r['filter_supported']}、降级 {r['filter_uncertain']}；再排除全部已人工审核和开发样本，仅 **{r['fresh_unreviewed_supported']} 条**可作为未审支持项。",
    f"新盲审目标 {r['fresh_sample_target']}，还缺 {r['fresh_sample_deficit']}；新种子已记录为 {r['fresh_seed']}，但没有抽取/发送新表。独立性、数量和可用过滤方案的条件均未同时满足。不会复用本次已调过规则的条目、重复抽样或把不确定项装进“过滤通过池”来凑表；原八列格式与最多错误{r['maximum_errors']}条的标准保持。",
    "这一步是未完成项。当前没有足够依据可给负责人一张合规的新盲审表，也不能继续旧流程的增量标注。",
    "## 下一步提案与需要的决定",
    "建议先完善“候选—具体细节—用户原句—关系绑定”的证据对齐版本，解决当前字符串原型的意译/指代误伤；只处理已有语料，保留原候选及失败记录。任何不支持细节仍必须拦截。候选改写、提示词修订或新模型复核若涉及冻结标注规程，先明确新候选版本、模型、提示词与整批复核范围，交负责人确认，不直接改冻结文件。",
    "请负责人决定是否批准这一证据对齐/新候选版本路径。批准过滤方案前，本轮未启动增量取样或标注，也未进行模型调用；不会以新数据填补当前规则造成的缺口。ECD、困难集人工审核继续暂缓，现有查询版本与裁判池不改；合成表仍缺稳定备选及人工校准，引用前轮报告。",
    "## 代码、验证与证据",
    f"完整检查：pytest **{validation['pytest']} passed / {validation['seconds']}s**；ruff、strict mypy通过；foundation {validation['foundation']}。原始日志见 validation.log，原数据/映射/人工标签只在.local。",
    f"本轮模型调用 **{r['model_calls']}**；所有核算和规则试验离线执行，没有新增标注费用/用量，没有换冻结模型。",
    "输入输出哈希、错误分类、全部分母、精度区间、验证版本见 report.json。ECD与原盲表、指标公式、通用审核阈值、已启用查询注册表散列已核对不变。",
    "```bash\nuv run python scripts/analyze-owner72-verbatim.py --output .local/reproduction-owner72-verbatim\nbash scripts/check.sh\nuv run python scripts/report-verbatim-filter.py\n```",
    "未完成：可用过滤方案、新独立盲审、增量补量、真实中文保底规模、完整负例会话确认、合成裁判备选及人工校准。阶段1未验收，不进入阶段2。",
]
text = "\n\n".join(s) + "\n"
text = re.sub(r"(\|[^\n]*\|)\n\n(?=\|)", r"\1\n", text)
(OUT / "delivery.md").write_text(text)
print(
    json.dumps(
        {
            "report": str(OUT / "delivery.md"),
            "gold": r["confirmed_positive_points"],
            "new_audit_created": r["fresh_audit_created"],
            "tests": validation["pytest"],
        }
    )
)
