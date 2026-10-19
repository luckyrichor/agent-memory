"""Named observation formulas; collection is separate from calculation.

Names encode the plan's numerator/denominator, so e.g. leaks cannot silently be
substituted for blocked samples. Curves are observations, not fake scalar scores.
"""

import math
from collections.abc import Sequence
from typing import Any

from agent_memory.evals.metrics import latency, ratio

RATIOS = {
    "EX1": ("correct_worthwhile", "extracted"),
    "EX2": ("gold_extracted", "gold_facts"),
    "EX4": ("unworthy_extracted", "extracted"),
    "EX5": ("attribution_errors", "extracted"),
    "EX6": ("sensitive_written", "sensitive_samples"),
    "EX7": ("normal_blocked", "normal_samples"),
    "LC1": ("duplicates_merged", "gold_duplicates"),
    "LC2": ("wrong_merges", "merges"),
    "LC3": ("correct_version", "conflicts"),
    "LC4": ("queries_with_stale_hits", "queries"),
    "LC5": ("illegal_rejected", "illegal_requests"),
    "RT6": ("correct_empty", "no_evidence_queries"),
    "CX1": ("actual_tokens", "budget_tokens"),
    "CX3": ("evidence_retained", "evidence_required"),
    "CX4": ("lost_key_info", "truncated_memories"),
    "CX5": ("redundant_items", "context_items"),
    "CX6": ("maintained_behavior", "injection_cases"),
    "E1": ("correct_answers", "questions"),
    "E3": ("total_tokens", "correct_answers"),
    "E4": ("unsupported_claims", "claims"),
    "E5": ("preferences_used_correctly", "preference_questions"),
    "E6": ("oracle_correct", "oracle_questions"),
    "RL4": ("eventual_success", "jobs"),
    "RL7": ("responses_5xx", "requests"),
}
COUNTS = {
    "LC7": ("content_copies", "vector_copies", "index_copies", "event_copies", "backup_copies"),
    "RT10": ("tenant_leaks", "user_leaks", "workspace_leaks"),
    "RL1": ("duplicate_rows", "same_key_mismatch_not_409"),
    "RL2": ("lost_updates",),
    "RL3": ("expired_worker_overwrites",),
    "SC1": ("cross_tenant_reads", "cross_tenant_writes"),
    "SC3": ("privilege_bypasses",),
    "SC4": ("raw_text_occurrences",),
    "SC8": ("outbound_text_count", "outbound_text_bytes"),
}
LATENCIES = {"EX9", "PF1", "PF2", "PF3", "PF7", "RL5", "OP1"}


def calculate(metric_id: str, rows: Sequence[dict[str, float]]) -> dict[str, Any]:
    if any(not math.isfinite(value) or value < 0 for row in rows for value in row.values()):
        raise ValueError("measurements must be finite and nonnegative")
    known = (
        set(RATIOS)
        | set(COUNTS)
        | LATENCIES
        | {
            "EX3",
            "EX8",
            "RT11",
            "SC5",
            "SC6",
            "SC7",
            "PF10",
            "SC2",
            "CX2",
            "PF4",
            "PF6",
            "PF8",
            "RL6",
        }
    )
    if not rows and metric_id in known:
        return {"n": 0, "status": "unavailable", "value": None}
    if metric_id == "CX2":
        return {
            "n": len(rows),
            "per_sample": [
                {
                    "signed_token_error": r["estimated_tokens"] - r["actual_tokens"],
                    "signed_relative_error": None
                    if r["actual_tokens"] == 0
                    else (r["estimated_tokens"] - r["actual_tokens"]) / r["actual_tokens"],
                    "unused_budget_fraction": None
                    if r["budget_tokens"] == 0
                    else (r["budget_tokens"] - r["actual_tokens"]) / r["budget_tokens"],
                    "budget_exceeded": r["actual_tokens"] > r["budget_tokens"],
                }
                for r in rows
            ],
            "definitions": "signed error uses actual tokens as denominator; unused fraction uses budget; negative indicates overflow, never clamped",
        }
    if metric_id == "PF4":
        targets = {r["p99_target_ms"] for r in rows}
        if len(targets) != 1:
            raise ValueError("do not mix throughput points with different latency budgets")
        eligible = [r["observed_qps"] for r in rows if r["p99_ms"] <= r["p99_target_ms"]]
        return {
            "n": len(rows),
            "max_observed_qps_within_budget": max(eligible) if eligible else None,
            "limits": "largest measured qualifying point, not an interpolated capacity claim",
        }
    if metric_id == "PF6":
        return {
            "neighbor_overlap": ratio([(r["neighbor_overlap"], r["k"]) for r in rows]).to_dict(),
            "latency_ms": latency([r["duration_ms"] for r in rows]),
            "build_ms_observations": [r["build_ms"] for r in rows],
            "index_bytes_observations": [r["index_bytes"] for r in rows],
            "definition": "ANN top-k overlap with exact neighbors, separate from semantic RT1",
        }
    if metric_id == "PF8":
        return {
            "retried_job_ratio": ratio([(r["retried_jobs"], r["jobs"]) for r in rows]).to_dict(),
            "dead_job_ratio": ratio([(r["dead_jobs"], r["jobs"]) for r in rows]).to_dict(),
            "processing_delay_ms": latency([r["processing_delay_ms"] for r in rows]),
            "backlog_observations": [r["backlog"] for r in rows],
        }
    if metric_id == "RL6":
        return {
            "restore_ms": latency([r["duration_ms"] for r in rows]),
            "row_count_mismatches": sum(r["row_count_mismatches"] for r in rows),
            "checksum_mismatches": sum(r["checksum_mismatches"] for r in rows),
            "sample_retrieval_failures": sum(r["sample_retrieval_failures"] for r in rows),
        }
    if metric_id in RATIOS:
        numerator, denominator = RATIOS[metric_id]
        if metric_id not in {"E3", "CX1"} and any(r[numerator] > r[denominator] for r in rows):
            raise ValueError("proportion numerator exceeds denominator")
        return ratio([(r[numerator], r[denominator]) for r in rows]).to_dict()
    if metric_id == "EX3":
        # Micro-F1 = 2TP/(2TP+FP+FN), bootstrap at supplied observation unit.
        return ratio([(2 * r["tp"], 2 * r["tp"] + r["fp"] + r["fn"]) for r in rows]).to_dict()
    if metric_id in COUNTS:
        return {
            "n": len(rows),
            "counts": {key: sum(r[key] for r in rows) for key in COUNTS[metric_id]},
        }
    if metric_id in LATENCIES:
        return latency([r["duration_ms"] for r in rows])
    if metric_id == "EX8":
        return {
            name: ratio([(r[field], r["events"]) for r in rows]).to_dict()
            for name, field in (("failure", "failed_events"), ("fallback", "rule_fallback_events"))
        }
    if metric_id == "RT11":
        return {
            "n": len(rows),
            "duplicates": sum(r["duplicate_results"] for r in rows),
            "omissions": sum(r["omitted_results"] for r in rows),
        }
    if metric_id in ("SC5", "SC6"):
        denominator = "writes" if metric_id == "SC5" else "queries"
        return {
            key + "_per_1000": ratio([(r[key] * 1000, r[denominator]) for r in rows]).to_dict()
            for key in ("calls", "input_tokens", "output_tokens")
        }
    if metric_id == "SC7":
        return {
            "hit_ratio": ratio([(r["hits"], r["queries"]) for r in rows]).to_dict(),
            "calls_saved": sum(r["calls_saved"] for r in rows),
            "tokens_saved": sum(r["tokens_saved"] for r in rows),
        }
    if metric_id == "PF10":
        # Ratio of measured p99s per tenant, not ratio of raw mean latencies.
        return {
            "n": len(rows),
            "per_tenant": [
                None if r["baseline_p99"] == 0 else r["loaded_p99"] / r["baseline_p99"]
                for r in rows
            ],
        }
    if metric_id == "SC2":
        return {
            "n": len(rows),
            "recall_drops": [r["before_recall"] - r["after_recall"] for r in rows],
        }
    raise ValueError(
        "metric is a retrieval calculation, compound observation or experiment; "
        "use its dedicated adapter, never manufacture a scalar: " + metric_id
    )
