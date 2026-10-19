"""Single offline scoring entry point. Live imports are in api_import.py.

This command consumes actual per-query source rankings, not answers. It does not
pretend to execute the service, a model, or a baseline when scoring a saved run.
"""

import argparse
import hashlib
import json
import platform
import subprocess
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent_memory.evals.datasets import Conversation, file_hash
from agent_memory.evals.metrics import evidence_retrieval, paired_difference, ratio, retrieval

SUPPORTED = {"RT1", "RT2", "RT3", "RT4", "RT5", "RT6"}


def score(
    dataset: Path, predictions: Path, *, ks: tuple[int, ...] = (1, 3, 5, 10)
) -> dict[str, Any]:
    rows = [json.loads(line) for line in predictions.read_text().splitlines() if line.strip()]
    predicted = {row["question_id"]: row for row in rows}
    if len(predicted) != len(rows):
        raise ValueError("duplicate prediction question ID")
    cases: list[dict[str, Any]] = []
    gold_ids: set[str] = set()
    with dataset.open() as stream:
        for line in stream:
            conv = Conversation.model_validate_json(line)
            for q in conv.questions:
                if q.question_id in gold_ids:
                    raise ValueError("duplicate gold question ID")
                gold_ids.add(q.question_id)
                record: dict[str, Any] = {
                    "question_id": q.question_id,
                    "conversation_id": conv.conversation_id,
                    "category": q.category,
                    "scores": {},
                }
                prediction = predicted.get(q.question_id)
                if prediction is None:
                    record["status"] = "missing_prediction"
                elif not q.evidence_available:
                    record["status"] = "unavailable_gold_evidence"
                else:
                    evidence_sets = prediction.get("ranked_evidence_sets")
                    ranked = prediction["ranked_source_ids"]
                    if not isinstance(ranked, list) or not all(isinstance(s, str) for s in ranked):
                        raise ValueError("ranking must contain source IDs")
                    if evidence_sets is not None and (
                        not isinstance(evidence_sets, list)
                        or any(
                            not isinstance(sources, list)
                            or not all(isinstance(s, str) for s in sources)
                            for sources in evidence_sets
                        )
                    ):
                        raise ValueError("invalid per-memory evidence sets")
                    record["rank_unit"] = "memory" if evidence_sets is not None else "source"
                    record["status"] = "scored"
                    if q.abstention:
                        # No post hoc low-confidence threshold. Empty is the supported RT6 criterion.
                        record["scores"]["RT6"] = float(not ranked)
                    else:
                        for k in ks:
                            computed = (
                                retrieval(ranked, q.relevant, k)
                                if evidence_sets is None
                                else evidence_retrieval(evidence_sets, q.relevant, k)
                            )
                            for name, value in computed.items():
                                record["scores"][f"{name}@{k}" if name != "RT3" else name] = value
                cases.append(record)
    units = {case["rank_unit"] for case in cases if "rank_unit" in case}
    if len(units) > 1:
        raise ValueError("cannot mix source and memory ranking units")
    if predicted.keys() - gold_ids:
        raise ValueError("prediction IDs absent from gold dataset")
    scores: dict[str, list[tuple[float, float]]] = defaultdict(list)
    by_type: dict[str, dict[str, list[tuple[float, float]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    # Cluster resampling at conversation level, including the question-level numerator/denominator.
    clusters: dict[tuple[str, str, str], list[float]] = defaultdict(list)
    for case in cases:
        for name, value in case["scores"].items():
            if value is not None:
                clusters[(case["conversation_id"], case["category"], name)].append(value)
    totals: dict[tuple[str, str], list[float]] = defaultdict(list)
    for (cid, category, name), values in clusters.items():
        by_type[category][name].append((sum(values), float(len(values))))
        totals[(cid, name)].extend(values)
    for (_, name), values in totals.items():
        scores[name].append((sum(values), float(len(values))))
    return {
        "cases": cases,
        "question_count": len(cases),
        "scored_count": sum(c["status"] == "scored" for c in cases),
        "metrics": {name: ratio(values).to_dict() for name, values in sorted(scores.items())},
        "by_type": {
            cat: {name: ratio(values).to_dict() for name, values in sorted(items.items())}
            for cat, items in sorted(by_type.items())
        },
        "ci_unit": "conversation cluster, 1000 bootstrap resamples",
        "precision_denominator": "k, including empty result slots",
        "ndcg_gain": "2**grade-1; no-evidence queries reported only as RT6",
        "rank_unit": next(iter(units), "unavailable"),
        "ndcg_unavailable_reason": "memory-item graded labels not supplied"
        if "memory" in units
        else None,
    }


def save_report(
    output: Path,
    dataset: Path,
    predictions: Path,
    config: Path,
    mode: str,
    metrics: set[str],
    *,
    baseline: Path | None = None,
) -> None:
    if metrics - SUPPORTED:
        raise ValueError(
            "requested metric adapter unavailable: " + ",".join(sorted(metrics - SUPPORTED))
        )
    # Reject before any writes; caller chooses an immutable date+commit+dataset directory.
    output.mkdir(parents=True, exist_ok=False)
    result = score(dataset, predictions)
    version = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], text=True))
    result["metadata"] = {
        "created_at": datetime.now(UTC).isoformat(),
        "commit": version,
        "uncommitted_changes": dirty,
        "dataset_sha256": file_hash(dataset),
        "predictions_sha256": file_hash(predictions),
        "config_sha256": file_hash(config),
        "mode": mode,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "seed": 42,
        "requested_metrics": sorted(metrics),
        "execution": "saved prediction scoring",
        "baseline": "B0 source tag only; NOT a phase2 quantitative baseline",
    }
    if baseline:
        previous = json.loads(baseline.read_text())
        if previous["metadata"]["dataset_sha256"] != result["metadata"]["dataset_sha256"]:
            raise ValueError("baseline uses different dataset hash")
        if previous.get("rank_unit") != result.get("rank_unit"):
            raise ValueError("baseline uses different ranking unit")
        if previous["metadata"]["mode"] != mode:
            raise ValueError("baseline uses different import mode")
        comparisons = {}
        for metric in result["metrics"]:
            before = {
                c["question_id"]: c["scores"][metric]
                for c in previous["cases"]
                if c["scores"].get(metric) is not None
            }
            after = {
                c["question_id"]: c["scores"][metric]
                for c in result["cases"]
                if c["scores"].get(metric) is not None
            }
            if before and before.keys() == after.keys():
                comparisons[metric] = paired_difference(before, after)
        result["paired_comparison"] = comparisons
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    (output / "report.json").write_text(payload)
    failures = [
        c["question_id"]
        for c in result["cases"]
        if c["status"] != "scored" or c["scores"].get("RT1@10") == 0
    ]
    lines = [
        "# 检索评测报告",
        "",
        f"源码：{version}；未提交修改：{dirty}",
        f"数据SHA256：{file_hash(dataset)}",
        f"模式：{mode}；执行方式：已有结果评分",
        "",
        "## 指标",
        "",
        "|指标|值|查询分母|重采样会话数|95% CI|",
        "|---|---|---|---|---|",
    ]
    for name, value in result["metrics"].items():
        lines.append(
            f"|{name}|{value['value']}|{value['denominator']}|{value['n']}|{value['ci95']}|"
        )
    lines.extend(
        [
            "",
            "## 失败与缺失",
            "",
            f"共{len(failures)}题；前20个ID：" + ", ".join(failures[:20]),
            "",
            "## 分题型、逐题、配对对比",
            "",
            "完整数据见同目录report.json。",
            "",
            "## 用量与边界",
            "",
            "本评分命令没有调用模型；原运行用量必须由采集端报告，当前未提供。",
            "rank_unit见report.json；来源单位与记忆单位不可混用，缺分级记忆金标时RT4不可用。",
            "缺失预测不默认算正确/错误，单独显示；不得在缺失未解释时声称完整质量结果。",
            "公开数据训练污染未确认；未进行裁判校准。",
        ]
    )
    (output / "report.md").write_text("\n".join(lines) + "\n")
    (output / "report.sha256").write_text(hashlib.sha256(payload.encode()).hexdigest() + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--mode", choices=("direct", "full"), required=True)
    parser.add_argument("--metrics", default="RT1,RT2,RT3,RT4,RT5,RT6")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline", type=Path)
    args = parser.parse_args()
    save_report(
        args.output,
        args.dataset,
        args.predictions,
        args.config,
        args.mode,
        set(args.metrics.split(",")),
        baseline=args.baseline,
    )


if __name__ == "__main__":
    main()
