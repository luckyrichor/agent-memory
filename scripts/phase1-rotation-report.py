"""Export aggregate migration evidence and restricted, genuinely unfilled human review packs."""

import argparse
import csv
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from agent_memory.evals.labeling import review_pack


def assert_aggregate_only(value):
    if isinstance(value, dict):
        if {"source", "candidate", "subject", "human_label", "human_reason"} & value.keys():
            raise ValueError("raw review fields must not enter aggregate report")
        for child in value.values():
            assert_aggregate_only(child)
    elif isinstance(value, list):
        for child in value:
            assert_aggregate_only(child)


parser = argparse.ArgumentParser()
parser.add_argument("--output", type=Path, required=True)
a = parser.parse_args()
a.output.mkdir(parents=True, exist_ok=False)
root = Path(".local/phase1")
report = {
    "generated_at": datetime.now(UTC).isoformat(),
    "generated_date_beijing": datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat(),
    "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
    "working_tree_modified": bool(
        subprocess.check_output(["git", "status", "--porcelain"], text=True).strip()
    ),
    "phase": 1,
    "phase_gate_passed": False,
    "human_review_complete": False,
    "human_review_policy": json.loads(Path("docs/evals/human-review-policy-v1.json").read_text()),
    "scope": "Model migration/preflight and candidate annotations; not approved gold or phase2 baseline.",
    "role_config_sha256": hashlib.sha256(
        Path("docs/evals/model-roles-v3.json").read_bytes()
    ).hexdigest(),
    "preflight": [],
    "datasets": [],
    "excluded_exploratory_models": ["kimi-k3"],
    "eligibility_audit_reference": "docs/reports/phase1-2026-10-19/model-eligibility-audit-v1.json",
}
for directory, model in [
    ("preflight-ark-pro21-v2", "doubao-seed-2-1-pro-260915"),
    ("preflight-deepseek-pro0813-v2", "deepseek-v4-pro-0813"),
    ("preflight-minimax-m27-v2", "minimax-m2.7"),
]:
    report["preflight"].append(
        json.loads((root / directory / (model + "-summary.json")).read_text())
    )
report["runtime_role_probe"] = json.loads((root / "ark-runtime-role-probe-v2.json").read_text())
for name, items_path, model_a, path_a, model_b, path_b in [
    (
        "synthetic-timeline",
        "timeline-v1/items.jsonl",
        "deepseek-v4.1-flash",
        "labels-a-v1",
        "minimax-m2.7",
        "timeline-labels-minimax27-v4-shards",
    ),
    (
        "public-chinese",
        "public-chinese-v1/items.jsonl",
        "glm-5.2",
        "public-labels-glm-v4",
        "deepseek-v4-pro-0813",
        "public-labels-deepseekpro-v4-shards4",
    ),
]:
    items = root / items_path
    item_count = len(items.read_text().splitlines())
    row = {
        "name": name,
        "candidate_count": item_count,
        "items_sha256": hashlib.sha256(items.read_bytes()).hexdigest(),
        "models": [model_a, model_b],
        "complete": False,
        "agreement": None,
    }
    left, right = root / path_a, root / path_b
    if (left / "COMPLETE").exists() and (right / "COMPLETE").exists():
        pack = root / ("human-review-" + name + "-rotation-v2")
        provenance = {
            "items_sha256": row["items_sha256"],
            "labels_sha256": [
                hashlib.sha256((p / "labels.jsonl").read_bytes()).hexdigest() for p in (left, right)
            ],
        }
        if not pack.exists():
            review_pack(items, left / "labels.jsonl", right / "labels.jsonl", pack)
            (pack / "provenance.json").write_text(json.dumps(provenance, indent=2))
        elif json.loads((pack / "provenance.json").read_text()) != provenance:
            raise ValueError("existing review pack provenance does not match frozen labels")
        metric = json.loads((pack / "model-agreement.json").read_text())
        for task in ("arbitration", "audit"):
            records = [
                json.loads(line)
                for line in (pack / (task + "-blind.jsonl")).read_text().splitlines()
            ]
            csv_path = pack / (task + "-blind.csv")
            if not csv_path.exists():
                with csv_path.open("w", encoding="utf-8-sig", newline="") as stream:
                    fields = [
                        "item_id",
                        "conversation_id",
                        "subject",
                        "candidate",
                        "source",
                        "record_sha256",
                        "human_label",
                        "human_reason",
                    ]
                    writer = csv.DictWriter(stream, fieldnames=fields)
                    writer.writeheader()
                    for original in records:
                        frozen = {k: v for k, v in original.items() if not k.startswith("human_")}
                        csv_row = {k: original.get(k, "") for k in fields}
                        if not isinstance(csv_row["source"], str):
                            csv_row["source"] = json.dumps(csv_row["source"], ensure_ascii=False)
                        csv_row["record_sha256"] = hashlib.sha256(
                            json.dumps(frozen, ensure_ascii=False, sort_keys=True).encode()
                        ).hexdigest()
                        csv_row["human_label"], csv_row["human_reason"] = "", ""
                        for key, value in csv_row.items():
                            if isinstance(value, str) and value.startswith(
                                ("=", "+", "-", "@", "\t", "\r")
                            ):
                                csv_row[key] = "'" + value
                        writer.writerow(csv_row)
        # IDs/text stay in restricted artifacts, aggregate counts only in Git.
        row["agreement"] = {
            k: v for k, v in metric.items() if k not in ("arbitration_ids", "audit_ids")
        }
        row["complete"] = True
        row["labels_sha256"] = provenance["labels_sha256"]
        row["human_review_directory"] = str(pack)
    report["datasets"].append(row)
report["limitations"] = [
    "Human arbitration/audit and judge calibration are not performed by the assistant.",
    "Synthetic templates are not evidence of real Chinese task quality.",
    "Public Chinese candidates are not approved gold; final accepted facts may be below target.",
    "Known failed/cancelled historical calls remain in .local; unknown delivery/usage is not zero.",
    "Model roles/prompts/batch sizes differ across datasets and are frozen separately.",
    "Public Chinese question generation/type coverage and other phase1 gates remain unaccepted.",
    "Original phase1 delivery and B0 tag remain historical, unchanged artifacts.",
]
assert_aggregate_only(report)
(a.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
lines = [
    "# agent-memory 阶段1：模型迁移与标注交接",
    "",
    f"执行：Codex；生成日期：{report['generated_date_beijing']}（北京时间）。",
    "",
    f"来源：agent-memory@{report['source_commit'][:7]}；未提交修改：{report['working_tree_modified']}。",
    "",
    "**阶段1尚未通过验收，未进入阶段2。** 本报告是阶段内交接，不是最终质量结论。",
    "",
    "## 新版模型",
    "",
    "用户已确认Ark抽取/答题改为doubao-seed-2-1-pro-260915。向量模型保持不变。",
    "",
    "| 模型 | 格式样本 | 5次一致 | 预检通过 |",
    "|---|---:|---|---|",
]
for p in report["preflight"]:
    lines.append(
        f"| {p['model']} | {p['format_valid']}/{p['format_n']} | {p['consistent_5']} | {p['preflight_pass']} |"
    )
lines += [
    "",
    "实际LLMExtractor最小合成请求200、1条候选、scope正确、没有降级；这不等于质量达标。",
    "",
    "## 完整标注与待人工审核",
    "",
    "| 数据 | 候选条数 | 双标注完整 | 一致性与人工材料 |",
    "|---|---:|---|---|",
]
for d in report["datasets"]:
    metric = d["agreement"]
    value = (
        f"κ={metric['kappa']:.3f}；分歧{metric['conflict_count']}；盲审{metric['audit_count']}；待人工"
        if metric and metric.get("kappa") is not None
        else "尚未完整配对或κ不可定义，不报告部分结果"
    )
    lines.append(f"| {d['name']} | {d['candidate_count']} | {d['complete']} | {value} |")
lines += [
    "",
    "两份盲审JSONL中的human_label/human_reason均为空，必须由负责人填写。",
    "模型κ门槛仍为0.7；负责人已明确批准10%盲审一致率至少95%；须用真实人工回填计算，不由助手代签。",
    "",
    "## 复现",
    "",
    "模型预检与标注入口见docs/evals/README.md；批次原文/响应/重试账本保存在.local/phase1。",
    "本报告由scripts/phase1-rotation-report.py自动生成；JSON保留数据/标签散列与限制。",
    "",
    "## 局限",
    "",
] + ["- " + x for x in report["limitations"]]
(a.output / "delivery.md").write_text("\n".join(lines) + "\n")
print(
    json.dumps(
        {
            "output": str(a.output),
            "datasets": [
                {k: d[k] for k in ("name", "candidate_count", "complete")}
                for d in report["datasets"]
            ],
        }
    )
)
