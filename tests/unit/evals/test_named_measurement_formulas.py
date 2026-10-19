import pytest

from agent_memory.evals.measurement_formulas import calculate


@pytest.mark.parametrize(
    "metric,observation,expected",
    [
        ("EX1", {"correct_worthwhile": 3, "extracted": 4}, 0.75),
        ("EX2", {"gold_extracted": 3, "gold_facts": 5}, 0.6),
        ("EX3", {"tp": 3, "fp": 1, "fn": 2}, 2 / 3),
        ("EX4", {"unworthy_extracted": 1, "extracted": 4}, 0.25),
        ("EX5", {"attribution_errors": 1, "extracted": 5}, 0.2),
        ("EX6", {"sensitive_written": 1, "sensitive_samples": 10}, 0.1),
        ("EX7", {"normal_blocked": 2, "normal_samples": 8}, 0.25),
        ("LC1", {"duplicates_merged": 3, "gold_duplicates": 4}, 0.75),
        ("LC2", {"wrong_merges": 1, "merges": 5}, 0.2),
        ("LC3", {"correct_version": 4, "conflicts": 5}, 0.8),
        ("LC4", {"queries_with_stale_hits": 1, "queries": 5}, 0.2),
        ("LC5", {"illegal_rejected": 7, "illegal_requests": 7}, 1),
        ("RT6", {"correct_empty": 2, "no_evidence_queries": 5}, 0.4),
        ("CX1", {"actual_tokens": 75, "budget_tokens": 100}, 0.75),
        ("CX3", {"evidence_retained": 2, "evidence_required": 3}, 2 / 3),
        ("CX4", {"lost_key_info": 1, "truncated_memories": 4}, 0.25),
        ("CX5", {"redundant_items": 2, "context_items": 5}, 0.4),
        ("CX6", {"maintained_behavior": 8, "injection_cases": 10}, 0.8),
        ("E1", {"correct_answers": 8, "questions": 10}, 0.8),
        ("E3", {"total_tokens": 900, "correct_answers": 3}, 300),
        ("E4", {"unsupported_claims": 2, "claims": 10}, 0.2),
        ("E5", {"preferences_used_correctly": 3, "preference_questions": 5}, 0.6),
        ("E6", {"oracle_correct": 9, "oracle_questions": 10}, 0.9),
        ("RL4", {"eventual_success": 8, "jobs": 10}, 0.8),
        ("RL7", {"responses_5xx": 1, "requests": 20}, 0.05),
    ],
)
def test_named_ratios_match_independent_hand_examples(metric, observation, expected):
    assert calculate(metric, [observation])["value"] == pytest.approx(expected)
    assert calculate(metric, [observation])["denominator"] > 0


def test_compound_formulas_have_separate_units_not_a_fake_combined_score():
    assert (
        calculate("EX8", [{"failed_events": 2, "rule_fallback_events": 1, "events": 10}])[
            "failure"
        ]["value"]
        == 0.2
    )
    assert calculate("RT11", [{"duplicate_results": 2, "omitted_results": 3}]) == {
        "n": 1,
        "duplicates": 2,
        "omissions": 3,
    }
    assert (
        calculate("SC5", [{"calls": 2, "input_tokens": 10, "output_tokens": 5, "writes": 100}])[
            "calls_per_1000"
        ]["value"]
        == 20
    )
    assert (
        calculate("SC6", [{"calls": 2, "input_tokens": 10, "output_tokens": 0, "queries": 100}])[
            "input_tokens_per_1000"
        ]["value"]
        == 100
    )
    assert (
        calculate("SC7", [{"hits": 3, "queries": 4, "calls_saved": 3, "tokens_saved": 90}])[
            "hit_ratio"
        ]["value"]
        == 0.75
    )
    assert calculate("PF10", [{"baseline_p99": 20, "loaded_p99": 30}])["per_tenant"] == [1.5]
    assert calculate("SC2", [{"before_recall": 0.8, "after_recall": 0.6}])[
        "recall_drops"
    ] == pytest.approx([0.2])
    assert (
        calculate("SC8", [{"outbound_text_count": 2, "outbound_text_bytes": 15}])["counts"][
            "outbound_text_bytes"
        ]
        == 15
    )
    with pytest.raises(ValueError, match="dedicated adapter"):
        calculate("OP2", [])


@pytest.mark.parametrize(
    "metric,fields,expected",
    [
        (
            "LC7",
            {
                "content_copies": 1,
                "vector_copies": 2,
                "index_copies": 0,
                "event_copies": 0,
                "backup_copies": 1,
            },
            {
                "content_copies": 2,
                "vector_copies": 4,
                "index_copies": 0,
                "event_copies": 0,
                "backup_copies": 2,
            },
        ),
        (
            "RT10",
            {"tenant_leaks": 1, "user_leaks": 0, "workspace_leaks": 2},
            {"tenant_leaks": 2, "user_leaks": 0, "workspace_leaks": 4},
        ),
        (
            "RL1",
            {"duplicate_rows": 1, "same_key_mismatch_not_409": 2},
            {"duplicate_rows": 2, "same_key_mismatch_not_409": 4},
        ),
        ("RL2", {"lost_updates": 2}, {"lost_updates": 4}),
        ("RL3", {"expired_worker_overwrites": 1}, {"expired_worker_overwrites": 2}),
        (
            "SC1",
            {"cross_tenant_reads": 1, "cross_tenant_writes": 2},
            {"cross_tenant_reads": 2, "cross_tenant_writes": 4},
        ),
        ("SC3", {"privilege_bypasses": 2}, {"privilege_bypasses": 4}),
        ("SC4", {"raw_text_occurrences": 1}, {"raw_text_occurrences": 2}),
    ],
)
def test_error_counts_are_absolute_not_normalized_away(metric, fields, expected):
    assert calculate(metric, [fields, fields]) == {"n": 2, "counts": expected}


@pytest.mark.parametrize("metric", ["EX9", "PF1", "PF2", "PF3", "PF7", "RL5", "OP1"])
def test_duration_metrics_have_hand_computable_percentiles(metric):
    result = calculate(metric, [{"duration_ms": 10}, {"duration_ms": 20}, {"duration_ms": 30}])
    assert result == pytest.approx({"n": 3, "p50": 20, "p95": 29, "p99": 29.8})


def test_invalid_observations_and_missing_fields_are_never_assumed_success():
    with pytest.raises(ValueError):
        calculate("LC5", [{"illegal_rejected": 4, "illegal_requests": 3}])
    with pytest.raises(ValueError):
        calculate("SC3", [{"privilege_bypasses": -1}])
    with pytest.raises(KeyError):
        calculate("LC7", [{"content_copies": 0}])


def test_context_counter_error_and_budget_overflow_have_explicit_denominators():
    sample = calculate(
        "CX2", [{"estimated_tokens": 120, "actual_tokens": 100, "budget_tokens": 150}]
    )["per_sample"][0]
    assert sample["signed_token_error"] == 20
    assert sample["signed_relative_error"] == 0.2
    assert sample["unused_budget_fraction"] == pytest.approx(1 / 3)
    overflow = calculate(
        "CX2", [{"estimated_tokens": 80, "actual_tokens": 100, "budget_tokens": 90}]
    )["per_sample"][0]
    assert overflow["budget_exceeded"] and overflow["unused_budget_fraction"] == pytest.approx(
        -1 / 9
    )


def test_capacity_selects_observed_qualifying_point_not_fictitious_interpolation():
    points = [
        {"observed_qps": q, "p99_ms": p, "p99_target_ms": 100}
        for q, p in [(10, 50), (20, 90), (30, 150)]
    ]
    assert calculate("PF4", points)["max_observed_qps_within_budget"] == 20
    assert calculate("PF4", [points[-1]])["max_observed_qps_within_budget"] is None


def test_ann_queue_restore_compound_metrics_are_not_collapsed():
    result = calculate(
        "PF6",
        [{"neighbor_overlap": 8, "k": 10, "duration_ms": 20, "build_ms": 200, "index_bytes": 1024}],
    )
    assert result["neighbor_overlap"]["value"] == 0.8
    assert result["index_bytes_observations"] == [1024]
    result = calculate(
        "PF8",
        [{"retried_jobs": 2, "dead_jobs": 1, "jobs": 10, "processing_delay_ms": 30, "backlog": 5}],
    )
    assert result["retried_job_ratio"]["value"] == 0.2 and result["dead_job_ratio"]["value"] == 0.1
    assert result["backlog_observations"] == [5]
    result = calculate(
        "RL6",
        [
            {
                "duration_ms": 100,
                "row_count_mismatches": 0,
                "checksum_mismatches": 1,
                "sample_retrieval_failures": 2,
            }
        ],
    )
    assert result["restore_ms"]["p99"] == 100 and result["checksum_mismatches"] == 1
    assert result["sample_retrieval_failures"] == 2
    assert calculate("SC1", []) == {"n": 0, "status": "unavailable", "value": None}
