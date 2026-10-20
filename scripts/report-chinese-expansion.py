"""Generate phase1 handoff and unfilled review artifacts from actual frozen files."""

import argparse
import json
import math
import subprocess
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from agent_memory.evals.chinese_expansion import MODELS, read_jsonl, write_jsonl
from agent_memory.evals.datasets import file_hash
from agent_memory.evals.labeling import load_labels, review_pack
from agent_memory.evals.reference_review import export_csv, make_reference_pack


def run_stats(root, directory):
    labels = []
    ledger = []
    observed_thinking = 0
    for path in sorted(directory.glob("shard-*/labels.jsonl")):
        labels.extend(read_jsonl(path))
    for path in sorted(directory.glob("shard-*/ledger.json")):
        ledger.extend(json.loads(path.read_text()))
    for entry in ledger:
        if entry.get("status") != "validated":
            continue
        cache = Path(".local/phase1/annotation-cache") / (entry["batch_hash"] + ".json")
        raw = json.loads(cache.read_text())["response"]
        message = raw["choices"][0]["message"]
        tokens = (
            (raw.get("usage") or {}).get("completion_tokens_details", {}).get("reasoning_tokens")
        )
        observed_thinking += bool(message.get("reasoning_content")) or (
            isinstance(tokens, int) and tokens > 0
        )
    usage = Counter()
    unknown = 0
    for entry in ledger:
        if entry.get("replayed"):
            continue
        if entry.get("usage"):
            for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                usage[key] += entry["usage"].get(key, 0)
        else:
            unknown += 1
    return {
        "directory": str(directory.relative_to(root)),
        "complete": (directory / "COMPLETE").exists(),
        "partial_label_count": len(labels),
        "observed_thinking_batches": observed_thinking,
        "sampling_policy_eligible": observed_thinking == 0,
        "http_statuses": dict(
            Counter(
                str(a["http_status"])
                for r in ledger
                for a in r.get("attempts", [])
                if "http_status" in a
            )
        ),
        "known_usage": dict(usage),
        "unknown_usage_batches": unknown,
        "ledger_sha256": [file_hash(p) for p in sorted(directory.glob("shard-*/ledger.json"))],
    }


p = argparse.ArgumentParser()
p.add_argument("--root", type=Path, default=Path(".local/phase1/chinese-expansion-v2"))
p.add_argument("--output", type=Path, required=True)
a = p.parse_args()
a.output.mkdir(parents=True, exist_ok=False)
root = a.root
pack_root = root / "human-review-v1"
pack_root.mkdir(exist_ok=False)
pack_root.chmod(0o700)
diagnosis = json.loads((root / "diagnosis.json").read_text())
results = []
for name in ("dulemon", "perltqa", "ecd"):
    directory = root / name
    manifest_file = directory / (
        "manifest-inherited-split.json" if name == "dulemon" else "manifest.json"
    )
    manifest = json.loads(manifest_file.read_text())
    if "source" in manifest:
        manifest["source_member"] = manifest.pop("source")
    items = directory / "items.jsonl"
    rows = read_jsonl(items)
    summary = {
        "name": name,
        "manifest": manifest,
        "items_sha256": file_hash(items),
        "models": None,
        "joint_keep": None,
        "kappa": None,
        "model_agreement": None,
        "model_arbitration_count": None,
        "audit_count": math.ceil(len(rows) / 10),
        "human_review_complete": False,
        "human_agreement": None,
        "gold_approved_by_owner": 0,
    }
    if name != "perltqa":
        dirs = [directory / f"labels-{model}-run1" for model in MODELS]
        stats = [run_stats(root, d) for d in dirs]
        summary["models"] = [{"model": model, **s} for model, s in zip(MODELS, stats)]
        if all(s["complete"] and s["sampling_policy_eligible"] for s in stats):
            target = pack_root / (name + "-model-review")
            review_pack(items, dirs[0] / "labels.jsonl", dirs[1] / "labels.jsonl", target)
            metric = json.loads((target / "model-agreement.json").read_text())
            left, right = (load_labels(d / "labels.jsonl") for d in dirs)
            summary.update(
                joint_keep=sum(left[k].label == right[k].label == "keep" for k in left),
                kappa=metric["kappa"],
                model_agreement={k: v for k, v in metric.items() if not k.endswith("_ids")},
                model_arbitration_count=metric["conflict_count"],
            )
            (target / "provenance.json").write_text(
                json.dumps(
                    {
                        "items_sha256": file_hash(items),
                        "labels_sha256": [file_hash(d / "labels.jsonl") for d in dirs],
                    },
                    indent=2,
                )
            )
            for task in ("arbitration", "audit"):
                export_csv(target / f"{task}-blind.jsonl")
    if name in ("dulemon", "perltqa"):
        # Corpus references never depend on model votes. This pack validates native
        # annotations, not model-selected labels. Model comparison stays separate.
        target = pack_root / (name + "-native-reference")
        review = make_reference_pack(items, directory / "references.jsonl", target)
        summary["native_reference_review"] = {
            k: v for k, v in review.items() if not k.endswith("_ids")
        }
        refs = load_labels(directory / "references.jsonl")
        summary["native_reference_keep"] = sum(r.label == "keep" for r in refs.values())
        summary["native_reference_discard"] = sum(r.label == "discard" for r in refs.values())
        summary["reference_keep_unique_texts"] = len(
            {r["candidate"] for r in rows if refs[r["item_id"]].label == "keep"}
        )
    if name == "ecd" and summary["model_arbitration_count"] is None:
        # Not an executable final audit: complete dual labels and owner arbitration
        # must first freeze the reference. No invented model labels or zero κ.
        import random

        wanted = set(
            random.Random(42).sample(sorted(r["item_id"] for r in rows), k=summary["audit_count"])
        )
        target = pack_root / "ecd-audit-pending-models"
        target.mkdir()
        write_jsonl(
            target / "audit-template-not-ready.jsonl",
            [
                {**r, "human_label": None, "human_reason": None}
                for r in rows
                if r["item_id"] in wanted
            ],
        )
        export_csv(target / "audit-template-not-ready.jsonl")
        (target / "README.txt").write_text(
            "仅冻结抽样ID的本地模板。双模型未完成，不存在最终参照，不可计算盲审一致率。ECD许可不明，本目录不对外发布。"
        )
        summary["audit_template_ready_for_final_scoring"] = False
    results.append(summary)

dule, perlt, ecd_summary = results
real_reference = dule["native_reference_keep"]
report = {
    "generated_at": datetime.now(UTC).isoformat(),
    "date_beijing": datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat(),
    "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
    "source_dirty": bool(
        subprocess.check_output(["git", "status", "--porcelain"], text=True).strip()
    ),
    "scope": "phase1 real Chinese source expansion only",
    "phase_gate_passed": False,
    "diagnosis": diagnosis,
    "datasets": results,
    "annotation_prompt_sha256": file_hash(Path("docs/evals/prompts/annotation-v4.txt")),
    "human_policy_sha256": file_hash(Path("docs/evals/human-review-policy-v1.json")),
    "annotation_models_requested": list(MODELS),
    "model_replacement_authorized": False,
    "metrics_or_semantic_guide_modified": False,
    "human_review_complete": False,
    "real_chinese": {
        "target": 1500,
        "new_original_conversations": dule["manifest"]["conversations"]
        + ecd_summary["manifest"]["conversations"],
        "new_candidates": dule["manifest"]["candidates"] + ecd_summary["manifest"]["candidates"],
        "new_corpus_reference_keep_unreviewed": real_reference,
        "corpus_reference_gap": max(0, 1500 - real_reference),
        "owner_approved_keep": 0,
        "owner_approved_gap": 1500,
        "new_reference_negative_conversations": dule["manifest"][
            "reference_negative_conversations"
        ],
        "ecd_negative_conversations": None,
        "negative_conversation_target_fraction": 0.3,
        "negative_conversation_gate_verified": False,
        "audit_count": dule["audit_count"] + ecd_summary["audit_count"],
        "arbitration_count": None,
        "note": "Native DuLeMon references do not depend on model votes. ECD lacks complete dual labels. PerLTQA and earlier synthetic timelines excluded. Historic old subset excluded to avoid silent redefinition and double counting.",
    },
    "minimax_probe": json.loads((root / "minimax-disabled-probe/report.json").read_text()),
    "deepseek_quota_retest": json.loads((root / "deepseek-quota-retest.json").read_text()),
    "excluded_initial_run": {
        "directory": "chinese-expansion-v1",
        "reason": "Persona field names in initial IDs risked leaking native references; stopped, replaced by opaque IDs in v2; no initial annotations accepted.",
        "runs": [
            run_stats(root.parent, directory)
            for directory in sorted(root.parent.glob("chinese-expansion-v1/*/labels-*-run1"))
        ],
        "note": "Interrupted calls can have unknown delivery/usage; unknown is not zero. No full billing-cost claim.",
    },
    "validation": json.loads((root / "validation-final/results.json").read_text()),
    "open_items": [
        "complete policy-compliant dual annotation and κ",
        "owner native-reference audit and ECD arbitration/audit",
        "at least30% negative original conversations",
        "judge human calibration",
        "Chinese query count and type coverage",
    ],
}


# No raw source/candidate/reason text in the public aggregate report.
def privacy_guard(value):
    if isinstance(value, dict):
        if {"source", "candidate", "subject", "human_label", "human_reason"} & value.keys():
            raise ValueError("raw source fields in public report")
        for v in value.values():
            privacy_guard(v)
    elif isinstance(value, list):
        for v in value:
            privacy_guard(v)


privacy_guard(report)
(a.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
lines = [
    "# agent-memory 阶段1：真实中文数据补量交接",
    "",
    f"执行：Codex；北京时间 {report['date_beijing']}；来源 agent-memory@{report['source_commit'][:7]}；未提交修改：{report['source_dirty']}。",
    "",
    "## 当前结论",
    "",
    "数据来源扩展与审核工具已准备；指定双模型受阻，双标未完成，阶段1未验收，不进入阶段2。",
    "",
    "## 旧候选诊断",
    "",
    f"候选 {diagnosis['candidate_count']}，共同保留 {diagnosis['joint_keep']}，未共同保留 {diagnosis['not_joint_keep']}。按旧模型原因码互斥归类，分歧优先，属于自动诊断而非人工真值。",
    "",
    "|原因|条数|代表记录ID（最多三个）|",
    "|---|---:|---|",
]
for category, bucket in diagnosis["categories"].items():
    lines.append(
        f"|{category}|{bucket['count']}|{'；'.join(bucket['example_ids']) or '无可确认例子，不编造'}|"
    )
lines += [
    "",
    "不通顺未被旧原因码单独测量：该类计数仅表示未单独归入，不证明语料没有不通顺。其他以来源缺证为主；不因模型拒绝而推翻语料原生参照。详细例子只在本地诊断附件。",
    "",
    "结论：保留标注指南与提示词的语义标准；改变来源处理（去分词空格、原生参照、增加语料），不以调低长期价值门槛提高保留率。旧对照模型实际为GLM-5.2与DeepSeek Pro，本轮按用户指定DeepSeek Pro与MiniMax 2.7，历史结果不混入新双标。",
    "",
    "## 新来源规模",
    "",
    "|来源|对话/分组|候选/原生记录|原生应记参照|共同保留|κ|",
    "|---|---:|---:|---:|---|---|",
]
for ds in results:
    m = ds["manifest"]
    lines.append(
        f"|{ds['name']}|{m['conversations']}|{m.get('candidates', m.get('native_memory_records'))}|{ds.get('native_reference_keep', '无原生标注')}|{ds['joint_keep'] if ds['joint_keep'] is not None else '未生成/不适用'}|{ds['kappa'] if ds['kappa'] is not None else '未生成/不适用'}|"
    )
lines += [
    "",
    f"DuLeMon：新增 {dule['manifest']['conversations']} 段未标注过的原始对话，抽样种子 {dule['manifest']['seed']}，与旧取样交集 {dule['manifest']['overlap']}；作者原生应记 {dule['native_reference_keep']}、不应记 {dule['native_reference_discard']}。原生参照不以模型共同保留筛选；模型仅做对照。",
    "",
    f"DuLeMon 应记候选的全局去重文字为 {dule['reference_keep_unique_texts']} 种；规模按会话内的来源标注点计数，不宣称都是不同语义事实。新样本继承已冻结全库切分：{dule['manifest']['source_frozen_split_counts']}；不重排旧会话，不用历史子集投影计算新评测。",
    "",
    f"PerLTQA：{perlt['manifest']['profile_groups']} 个角色分组，{perlt['manifest']['conversations']} 段对话、{perlt['native_reference_keep']} 条原生记忆记录（含档案/关系/事件/对话，不冒充原子抽取事实）。按原生标注使用，未做双模型筛选，因此共同保留、κ不适用。该数据为作者以GPT-3.5生成并人工修订，归公开合成基准，真实中文贡献为 {perlt['manifest']['real_chinese_count_contribution']}。",
    "",
    "PerLTQA来源：[论文](https://aclanthology.org/2024.sighan-1.18/)、[仓库](https://github.com/Elvin-Yiming-Du/PerLTQA)、[CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/)。不修改原标注，不把它冒称真实人类对话。",
    "",
    f"ECD：压缩包 {ecd_summary['manifest']['archive_bytes']} 字节、CRC通过。训练集正/负回复行分别 {ecd_summary['manifest']['positive_response_rows']}/{ecd_summary['manifest']['negative_response_rows']}，去重后正例上下文 {ecd_summary['manifest']['unique_positive_contexts']}；种子 {ecd_summary['manifest']['seed']} 抽取 {ecd_summary['manifest']['conversations']} 段。候选为原始话语，不经模型预筛。去除分词ASCII空格，不添加客户/客服角色；原文无角色标签。0/1只是回复匹配，不是记忆标签，更不是负样本对话比例。许可未明：原始数据及审核原文仅在.local，本仓库只存清单/哈希、方法和指标。",
    "",
    "ECD来源：[原仓库](https://github.com/cooelf/DeepUtteranceAggregation)、[论文](https://arxiv.org/abs/1806.09102)。",
    "",
    "## 模型与阻塞",
    "",
]
for ds in (dule, ecd_summary):
    for s in ds["models"]:
        lines.append(
            f"- {ds['name']} / {s['model']}：仅部分标签 {s['partial_label_count']}，COMPLETE={s['complete']}；观察到思考输出的批次数 {s['observed_thinking_batches']}；HTTP状态计数 {s['http_statuses']}。不计算完整双模型κ或共同保留数。"
        )
lines += [
    "",
    f"DeepSeek最小复测HTTP {report['deepseek_quota_retest']['http_status']}，供应商码 {report['deepseek_quota_retest']['provider_code']}：免费试用额度耗尽、未开后付费。未充值、未开付费。MiniMax请求关闭思考，但实际响应含推理内容，复测确认关闭行为={report['minimax_probe']['disabled_behavior_confirmed']}。依据[官方MiniMax参数文档](https://intl.cloud.tencent.com/zh/document/product/1300/80636)应支持disabled，当前接口行为与请求不一致。未擅自换模型，等待负责人决定。",
    "",
    "已增加响应侧检查：请求被接受不能证明参数生效；返回思考内容/正推理token时拒绝正式接收该批。已接收部分标签不静默修补、补齐或混为完整结果。",
    "",
    "## 目标与人工交接",
    "",
    f"真实中文新增原始对话 {report['real_chinese']['new_original_conversations']}，候选 {report['real_chinese']['new_candidates']}；原生应记参照（未人工抽检）{real_reference}，相对1500的参照缺口 {report['real_chinese']['corpus_reference_gap']}。负责人已批准金标 {report['real_chinese']['owner_approved_keep']}，已批准口径距目标 {report['real_chinese']['owner_approved_gap']}，不能据参照量宣布验收。旧合成时间线及PerLTQA均不计真实规模。",
    "",
    f"DuLeMon本批整段负样本对话 {dule['manifest']['reference_negative_conversations']}。ECD整段负样本须待双标及负责人审核确定，目前未知；未验证≥30%，不拿不应记人设比例或回复匹配负例比例代替。",
    "",
    f"新增真实中文10%盲审抽样：DuLeMon {dule['audit_count']}，ECD {ecd_summary['audit_count']}，合计 {report['real_chinese']['audit_count']}；ECD当前仅冻结抽样ID的待双标模板，不可计算一致率。PerLTQA原生参照另抽检 {perlt['audit_count']}，不并入真实中文规模。仲裁总条数未确定：完整双标尚缺，不能用部分分歧数冒充最终条数。",
    "",
    "DuLeMon与PerLTQA原生参照抽检包已生成，human_label/human_reason全空；助手没有代填。ECD最终仲裁及审计包待完整双标后生成。κ≥0.7、10%盲审一致率≥95%保持不变。原生参照审核独立于模型筛选；不通过时修正参照，仍按审核更正前的冻结参照计算一致率。",
    "",
    "剩余：完整双标与κ；负责人抽检/仲裁；真实负样本对话比例；裁判人工校准；中文查询数量与题型覆盖。所有结论仅限当前实际取样规模，不扩大到生产场景。",
    "",
    "## 验证",
    "",
]
for gate in report["validation"]:
    lines.append(
        f"- {gate['name']}：退出码 {gate['exit_code']}，{gate['seconds']:.2f}秒；命令 `{' '.join(gate['command'])}`。"
    )
lines += [
    "",
    "原始日志在本地validation-final；原始语料、模型响应、部分标签、未知用量均留在.local，不对外暴露。聚合报告由本脚本生成，数字不手填。",
]
(a.output / "delivery.md").write_text("\n".join(lines) + "\n")
private = root / "diagnostic-examples.md"
example_rows = read_jsonl(root / "diagnostic-examples-local.jsonl")
text = [
    "# 旧候选诊断代表例子（本地审核附件，不提交Git）",
    "",
    "以下只是旧模型原因码归类的例子，并非助手的人工仲裁。归属/长期价值的判定仍可由负责人纠正。",
]
for category, bucket in diagnosis["categories"].items():
    text += ["", f"## {category}（{bucket['count']}条）", ""]
    examples = [r for r in example_rows if r["category"] == category]
    for row in examples:
        text.append(f"- {row['item_id']}：{row['candidate']}")
    if not examples:
        text.append("旧原因码无法确认该类例子；不编造三个例子。完整候选与来源保留在本地JSONL。")
private.write_text("\n".join(text) + "\n")
print(
    json.dumps(
        {
            "phase_gate_passed": False,
            "real_unreviewed_reference_keep": real_reference,
            "new_real_audit_samples": report["real_chinese"]["audit_count"],
            "model_arbitration_count": None,
        }
    )
)
