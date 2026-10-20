"""Complete-only replacement-pair report; never publish raw ECD or human answers."""

import argparse
import json
import subprocess
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from agent_memory.evals.chinese_expansion import read_jsonl
from agent_memory.evals.datasets import file_hash
from agent_memory.evals.labeling import load_labels, review_pack
from agent_memory.evals.reference_review import export_csv, make_reference_pack

p = argparse.ArgumentParser()
p.add_argument("--root", type=Path, default=Path(".local/phase1/chinese-rotation-v1"))
p.add_argument("--output", type=Path, required=True)
a = p.parse_args()
root = a.root
data = Path(".local/phase1/chinese-expansion-v2")
frozen = json.loads((root / "frozen-run.json").read_text())
models = [r["model"] for r in frozen["qualifications"]]
assert len(models) == 2
report = {
    "generated_at": datetime.now(UTC).isoformat(),
    "date_beijing": datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat(),
    "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
    "working_tree_modified": bool(
        subprocess.check_output(["git", "status", "--porcelain"], text=True).strip()
    ),
    "phase_gate_passed": False,
    "human_review_complete": False,
    "replacement_authorized": True,
    "models": models,
    "scope": "Full independent replacement annotations of unchanged phase1 source samples",
    "frozen": frozen,
    "datasets": [],
    "preflights": [
        json.loads(path.read_text()) for path in sorted(root.glob("preflight-*/*-summary.json"))
    ],
    "source_files_match_frozen": all(
        file_hash(Path(path)) == sha for path, sha in frozen["source_files"].items()
    ),
    "diagnosis": json.loads((data / "diagnosis.json").read_text()),
    "thresholds": {"model_kappa": 0.7, "human_agreement": 0.95, "audit_fraction": 0.1, "seed": 42},
}
packs = root / "human-review-v1"
packs.mkdir(exist_ok=False)
packs.chmod(0o700)
for name in ("dulemon", "ecd"):
    items_path = data / name / "items.jsonl"
    rows = read_jsonl(items_path)
    ids = [r["item_id"] for r in rows]
    paths = [root / name / ("labels-" + model + "-run1") for model in models]
    for path in paths:
        if not (path / "COMPLETE").exists() or (path / "COMPLETE").read_text().strip() != file_hash(
            items_path
        ):
            raise ValueError("Incomplete or mismatched annotation: " + str(path))
    left, right = [load_labels(path / "labels.jsonl") for path in paths]
    if set(ids) != left.keys() or left.keys() != right.keys():
        raise ValueError("full label coverage required")
    target = packs / (name + "-model-comparison")
    review_pack(items_path, paths[0] / "labels.jsonl", paths[1] / "labels.jsonl", target)
    provenance = {
        "items_sha256": file_hash(items_path),
        "labels_sha256": [file_hash(path / "labels.jsonl") for path in paths],
    }
    (target / "provenance.json").write_text(json.dumps(provenance, indent=2))
    for task in ("arbitration", "audit"):
        export_csv(target / (task + "-blind.jsonl"))
    metric = json.loads((target / "model-agreement.json").read_text())
    group = {}
    for row in rows:
        group.setdefault(row["conversation_id"], []).append(row["item_id"])
    confirmed_negative = sum(
        all(left[k].label == right[k].label == "discard" for k in keys) for keys in group.values()
    )
    summary = {
        "name": name,
        "conversations": len(group),
        "candidates": len(rows),
        "models": models,
        "label_files_sha256": provenance["labels_sha256"],
        "joint_keep": sum(left[k].label == right[k].label == "keep" for k in ids),
        "joint_discard": sum(left[k].label == right[k].label == "discard" for k in ids),
        "model_agreement": {
            k: v for k, v in metric.items() if k not in ("arbitration_ids", "audit_ids")
        },
        "kappa_passed": metric["kappa"] is not None and metric["kappa"] >= 0.7,
        "model_disagreement_arbitration": metric["conflict_count"],
        "audit_count": metric["audit_count"],
        "all_candidate_consensus_discard_conversations": confirmed_negative,
        "owner_approved_gold": 0,
        "human_agreement": None,
    }
    if name == "dulemon":
        refs_path = data / name / "references.jsonl"
        refs = load_labels(refs_path)
        make_reference_pack(items_path, refs_path, packs / "dulemon-native-reference")
        summary["native_reference_keep"] = sum(r.label == "keep" for r in refs.values())
        summary["native_reference_discard"] = sum(r.label == "discard" for r in refs.values())
        summary["reference_keep_unique_texts"] = len(
            {r["candidate"] for r in rows if refs[r["item_id"]].label == "keep"}
        )
        summary["comparisons_against_native"] = [
            {
                "model": model,
                "matches": sum(labels[k].label == refs[k].label for k in ids),
                "agreement": sum(labels[k].label == refs[k].label for k in ids) / len(ids),
                "matrix": dict(Counter(refs[k].label + "/" + labels[k].label for k in ids)),
            }
            for model, labels in zip(models, (left, right))
        ]
        summary["native_negative_conversations"] = json.loads(
            (data / name / "manifest-inherited-split.json").read_text()
        )["reference_negative_conversations"]
        summary["native_gold_not_filtered_by_models"] = True
    report["datasets"].append(summary)

dule, ecd = report["datasets"]
report["real_chinese"] = {
    "original_conversations": dule["conversations"] + ecd["conversations"],
    "candidates": dule["candidates"] + ecd["candidates"],
    "native_dulemon_keep_unreviewed": dule["native_reference_keep"],
    "ecd_consensus_keep_unreviewed": ecd["joint_keep"],
    "provisional_keep_occurrences": dule["native_reference_keep"] + ecd["joint_keep"],
    "reference_gap_to_1500": max(0, 1500 - dule["native_reference_keep"] - ecd["joint_keep"]),
    "owner_approved_keep": 0,
    "owner_approved_gap": 1500,
    "negative_original_conversations_provisional": ecd[
        "all_candidate_consensus_discard_conversations"
    ],
    "negative_fraction_provisional": ecd["all_candidate_consensus_discard_conversations"]
    / (dule["conversations"] + ecd["conversations"]),
    "negative_fraction_target": 0.3,
    "negative_fraction_human_verified": False,
    "model_disagreements_total": dule["model_disagreement_arbitration"]
    + ecd["model_disagreement_arbitration"],
    "ecd_required_arbitration": ecd["model_disagreement_arbitration"],
    "audit_samples": dule["audit_count"] + ecd["audit_count"],
    "note": "DuLeMon native references used directly, models only compared; ECD consensus requires owner arbitration/audit. PerLTQA and synthetic timelines excluded. A whole negative conversation requires all original-utterance candidates jointly discarded; any uncertain item prevents negative classification.",
}
report["model_kappa_gates_passed"] = all(d["kappa_passed"] for d in report["datasets"])
usage = Counter()
unknown = 0
for path in sorted(root.glob("**/shard-*/ledger.json")):
    for record in json.loads(path.read_text()):
        if record.get("replayed"):
            continue
        if record.get("usage"):
            for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                usage[key] += record["usage"].get(key, 0)
        else:
            unknown += 1
report["annotation_usage"] = {
    "known_tokens": dict(usage),
    "unknown_usage_batches": unknown,
    "scope": "Child ledgers only; parent aggregate ledgers not summed twice. Preflights, previous failed models excluded from this subtotal; not account-wide billing.",
}
previous = Path(".local/phase1/chinese-rotation-v1")
if previous != root:
    previous_stats = []
    for model in ("deepseek-v4-pro-202606", "glm-5.2"):
        totals = Counter()
        states = []
        for name in ("dulemon", "ecd"):
            directory = previous / name / ("labels-" + model + "-run1")
            entries = [
                r
                for path in directory.glob("shard-*/ledger.json")
                for r in json.loads(path.read_text())
            ]
            for entry in entries:
                if not entry.get("replayed"):
                    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                        totals[key] += (entry.get("usage") or {}).get(key, 0)
            states.append(
                {
                    "dataset": name,
                    "complete": (directory / "COMPLETE").exists(),
                    "partial_labels": sum(
                        len(path.read_text().splitlines())
                        for path in directory.glob("shard-*/labels.jsonl")
                    ),
                    "http_statuses": dict(
                        Counter(
                            str(a["http_status"])
                            for r in entries
                            for a in r.get("attempts", [])
                            if "http_status" in a
                        )
                    ),
                }
            )
        previous_stats.append({"model": model, "known_usage": dict(totals), "datasets": states})
    report["previous_rotation"] = {
        "directory": str(previous),
        "models": previous_stats,
        "note": "Completed same-version DeepSeek side replayed through identical request cache; failed partial GLM side excluded. This is complete single-model reuse, never mixing different models into one label file.",
    }
report["open_items"] = [
    "owner native-reference audit, ECD arbitration and blind audit",
    "human-verified >=30% original negative conversations",
    "judge human calibration",
    "Chinese queries and per-type coverage",
]


def no_source(value):
    if isinstance(value, dict):
        if {"source", "candidate", "subject", "human_label", "human_reason"} & value.keys():
            raise ValueError("raw review fields in public report")
        for child in value.values():
            no_source(child)
    elif isinstance(value, list):
        for child in value:
            no_source(child)


no_source(report)
a.output.mkdir(parents=True, exist_ok=False)
(a.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
lines = [
    "# agent-memory 阶段1：替代模型完整双标交接",
    "",
    f"执行：Codex；北京时间 {report['date_beijing']}；代码 agent-memory@{report['source_commit'][:7]}；存在未提交修改：{report['working_tree_modified']}。",
    "",
    "## 结论",
    "",
    "完整双模型标注已完成；人工仲裁/盲审尚未完成，阶段1未验收，不进入阶段2。",
    "",
    f"新组合：{' + '.join(models)}。用户授权后自动替换；原DeepSeek Pro0813因免费额度耗尽、MiniMax2.7因关闭思考不生效退出本轮正式组合。原始实验不覆盖，部分标签不混用。",
    "",
    "## 预检与实验冻结",
    "",
]
for pre in report["preflights"]:
    lines.append(
        f"- {pre['model']}：格式 {pre['format_valid']}/{pre['format_n']}，5次一致={pre['consistent_5']}，预检通过={pre['preflight_pass']}；观测到关闭思考={pre['observed_disabled_thinking']}。"
    )
lines += [
    "",
    "指南语义、提示词、原始候选/来源、原生参照、切分和阈值保持。内部编号仅在传输中使用可逆短别名，输出恢复原ID；来源、角色和记忆主体文本逐字保留。新请求缓存与旧请求不混同。预检只验证可访问性/格式/重复一致性/响应参数行为，不冒充裁判人工校准。",
    "",
    "[DeepSeek官方指南](https://intl.cloud.tencent.com/zh/document/product/1300/80633)、[GLM官方指南](https://cloud.tencent.com/document/product/1823/132061)、[MiMo官方指南](https://intl.cloud.tencent.com/zh/document/product/1300/84216)。GLM-5.2在首轮完整标注中也遇到402，部分结果留档；GLM-5.3系列官方不支持关闭思考，未进入正式候选。已完成的同版本DeepSeek整侧通过相同请求缓存验证复用，另一厂商完整独立重标。",
    "",
    "## 数据与一致性",
    "",
    "|来源|原始对话|候选|共同保留|共同舍弃|κ|分歧或不确定|10%抽检|",
    "|---|---:|---:|---:|---:|---:|---:|---:|",
]
for d in report["datasets"]:
    lines.append(
        f"|{d['name']}|{d['conversations']}|{d['candidates']}|{d['joint_keep']}|{d['joint_discard']}|{d['model_agreement']['kappa']}|{d['model_disagreement_arbitration']}|{d['audit_count']}|"
    )
lines += [
    "",
    f"模型κ门槛≥0.7：{report['model_kappa_gates_passed']}。不得因为共同保留数较少就降低门槛；低于门槛时报告失败，并只分析开发集的规则理解/来源问题。",
    "",
    f"DuLeMon原生应记 {dule['native_reference_keep']}、不应记 {dule['native_reference_discard']}，应记参照含 {dule['reference_keep_unique_texts']} 种去重文字；模型共同保留数不能替代或筛除这些原生标注。模型对原生标签的比较：",
    "",
]
for comparison in dule["comparisons_against_native"]:
    lines.append(
        f"- {comparison['model']}：原生参照一致率 {comparison['agreement']:.6f}；匹配 {comparison['matches']}/{dule['candidates']}；原生/模型标签矩阵 {comparison['matrix']}。这不是人工审核一致率。"
    )
real = report["real_chinese"]
lines += [
    "",
    f"真实中文未审核记忆点参照合计 {real['provisional_keep_occurrences']}（DuLeMon原生 {real['native_dulemon_keep_unreviewed']} + ECD双模型共同保留 {real['ecd_consensus_keep_unreviewed']}），相对1500的参照缺口 {real['reference_gap_to_1500']}。人工确认金标仍为 {real['owner_approved_keep']}，阶段目标尚未验收。规模按会话内标注点出现次数计，不宣称是全局不同事实。",
    "",
    f"ECD中全部候选均被双模型共同舍弃的原始会话 {real['negative_original_conversations_provisional']}，在本轮真实原始对话 {real['original_conversations']} 中占 {real['negative_fraction_provisional']:.6%}；这是暂定负样本比例，人工未核验。DuLeMon没说过人设不等于整段负样本，ECD回复匹配标签不计作记忆标签，未知或不确定不强行算负例。",
    "",
    "PerLTQA已按原生标注接入，但论文确认其由模型生成并人工修订，单列公开合成基准，不加入真实中文规模；对应原生审核包保留上一轮版本。[来源论文](https://aclanthology.org/2024.sighan-1.18/)、[仓库及许可](https://github.com/Elvin-Yiming-Du/PerLTQA)。",
    "",
    "## 人工交接与许可",
    "",
    f"本轮两个模型的分歧/不确定总计 {real['model_disagreements_total']}；其中ECD需负责人仲裁 {real['ecd_required_arbitration']}。真实中文抽检 {real['audit_samples']}，按来源分别上取整、种子42。DuLeMon模型分歧仅供原生标注对照，原生参照审核另用native-reference包；不自动改原生金标，不要求重复填写两份相同抽检。",
    "",
    "所有human_label/human_reason为空；负责人回填后按更正前的冻结参照计算盲审一致率，要求≥95%；不能先改参照再算成100%。只有负责人一人仲裁，需注明单人仲裁局限。",
    "",
    "ECD许可未知，原始语料、完整响应及仲裁/审核原文留在服务器.local，GitHub及外发材料只含方法、哈希和指标。DuLeMon与PerLTQA原始数据不进Git。原生/模型审核包的路径、输入哈希和请求配置见本地冻结清单。",
    "",
    "仍未完成：负责人回填与盲审、负样本比例的人审确认、裁判人工校准、中文查询数量和题型覆盖。无阶段2调用，无验收通过声明。",
    "",
    f"新标注请求已知token小计：{dict(usage)}；未知用量批次 {unknown}。这不是整个账户账单；旧失败/中断请求及预检另留台账。所有数字由report-chinese-rotation.py生成。",
]
(a.output / "delivery.md").write_text("\n".join(lines) + "\n")
print(
    json.dumps(
        {
            "datasets": [
                {
                    "name": d["name"],
                    "kappa": d["model_agreement"]["kappa"],
                    "joint_keep": d["joint_keep"],
                }
                for d in report["datasets"]
            ],
            "phase_gate_passed": False,
        }
    )
)
