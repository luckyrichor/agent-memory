import math

import pytest

from agent_memory.evals.metrics import clopper_pearson


def test_all_successes_and_all_failures_have_non_degenerate_closed_forms():
    expected = 0.025 ** (1 / 72)
    assert clopper_pearson(72, 72) == pytest.approx((expected, 1))
    assert clopper_pearson(0, 72) == pytest.approx((0, 1 - expected))
    assert clopper_pearson(1, 1) == pytest.approx((0.025, 1))
    assert clopper_pearson(0, 0) is None


def test_exact_interval_matches_published_nist_example_and_symmetry():
    # NIST handbook exact two-sided 90% interval for 4/20.
    low, high = clopper_pearson(4, 20, confidence=0.9)
    assert low == pytest.approx(0.071354, abs=5e-7)
    # The handbook's displayed last decimal is approximate; verify the exact tail too.
    assert high == pytest.approx(0.401029, abs=1e-6)
    cdf = sum(math.comb(20, k) * high**k * (1-high)**(20-k) for k in range(5))
    assert cdf == pytest.approx(0.05, abs=1e-12)
    mirrored = clopper_pearson(16, 20, confidence=0.9)
    assert mirrored == pytest.approx((1 - high, 1 - low))


@pytest.mark.parametrize('s,n,c', [(-1, 10, .95), (11, 10, .95), (0, -1, .95),
                                  (1, 1, 1), (1, 1, 0), (1, 1, float('nan'))])
def test_invalid_binomial_inputs_rejected(s, n, c):
    with pytest.raises(ValueError):
        clopper_pearson(s, n, confidence=c)
