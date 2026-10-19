import math

import pytest

from agent_memory.evals.metrics import (
    agreement,
    f1,
    latency,
    paired_difference,
    quantile,
    ratio,
    retrieval,
)


def test_ratio_hand_calculated_and_seeded_ci():
    value = ratio([(1, 2), (2, 4)], seed=1)
    assert value.value == 0.5
    assert value.numerator == 3 and value.denominator == 6 and value.n == 2
    assert value.ci95 == (0.5, 0.5)
    # Cost per correct answer may be >1; it is not a Bernoulli proportion.
    assert ratio([(120, 2), (60, 1)]).value == 60
    assert ratio([(0, 0)]).value is None
    assert ratio([]).ci95 is None


def test_f1_hand_calculated():
    assert f1(0.5, 1) == pytest.approx(2 / 3)
    assert f1(0, 0) == 0
    assert f1(None, 1) is None


def test_retrieval_hand_calculated():
    result = retrieval(["wrong", "b", "a"], {"a": 3, "b": 1}, 3)
    assert result["RT1"] == 1
    assert result["evidence_coverage"] == 1
    assert result["RT2"] == pytest.approx(2 / 3)
    assert result["RT3"] == 0.5
    expected = (1 / math.log2(3) + 7 / 2) / (7 + 1 / math.log2(3))
    assert result["RT4"] == pytest.approx(expected)
    assert retrieval(["a"], {"a": 1, "b": 1}, 3)["RT2"] == pytest.approx(1 / 3)
    assert retrieval(["a"], {"a": 1, "b": 1}, 3)["evidence_coverage"] == 0.5
    assert retrieval([], {"a": 1}, 3)["RT1"] == 0
    assert retrieval([], {}, 3)["RT1"] is None
    assert retrieval([], {}, 3)["RT3"] is None


def test_percentiles_hand_calculated():
    assert latency([10, 20, 30, 40]) == pytest.approx({"n": 4, "p50": 25, "p95": 38.5, "p99": 39.7})
    assert latency([])["p99"] is None
    assert quantile([3], 0.99) == 3


def test_kappa_hand_calculated():
    # p_o=.75; p_e=.5; kappa=.5
    result = agreement(["yes", "yes", "no", "no"], ["yes", "no", "no", "no"])
    assert result["kappa"] == 0.5 and result["agreement"] == 0.75
    assert agreement(["yes"], ["yes"])["kappa"] is None
    assert agreement([], [])["agreement"] is None


def test_paired_difference_hand_calculated():
    result = paired_difference({"a": 0, "b": 1}, {"a": 1, "b": 0})
    assert result["delta"] == 0
    assert result["ci95"] == [-1, 1]
    assert result["increased"] == ["a"] and result["decreased"] == ["b"]
    assert not result["excludes_zero"]
    result = paired_difference({"a": 0, "b": 0}, {"a": 1, "b": 1})
    assert result["delta"] == 1 and result["excludes_zero"]


@pytest.mark.parametrize(
    "operation",
    [
        lambda: ratio([(float("nan"), 1)]),
        lambda: ratio([(-1, 1)]),
        lambda: latency([-1]),
        lambda: quantile([float("inf")], 0.5),
        lambda: retrieval(["a", "a"], {"a": 1}, 3),
        lambda: retrieval([], {}, 0),
        lambda: agreement(["yes"], []),
        lambda: paired_difference({"a": 1}, {"b": 1}),
    ],
)
def test_invalid_data_cannot_silently_pass(operation):
    with pytest.raises(ValueError):
        operation()


def test_memory_ranking_does_not_collapse_duplicate_sources_or_lose_merged_evidence():
    from agent_memory.evals.metrics import evidence_retrieval

    gold = {"s1": 1, "s2": 1}
    merged = evidence_retrieval([["s1", "s2"]], gold, 3)
    assert merged["RT1"] == 1 and merged["evidence_coverage"] == 1
    assert merged["RT2"] == pytest.approx(1 / 3) and merged["RT3"] == 1
    duplicate_sources = evidence_retrieval([["s1"], ["s1"], ["wrong"]], gold, 3)
    assert duplicate_sources["RT2"] == pytest.approx(2 / 3)
    assert duplicate_sources["evidence_coverage"] == 0.5
    assert duplicate_sources["RT4"] is None
