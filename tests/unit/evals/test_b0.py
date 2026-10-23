import pytest

from agent_memory.evals.b0 import (
    calibration_sample,
    cosine_rank,
    development_ids,
    sample_development,
)


def test_dev_isolation_and_stable_sampling():
    rows = [{'conversation_id': str(i), 'answer': 'private'} for i in range(8)]
    split = {'dev': ['0', '2', '4', '6'], 'test': ['1', '3', '5', '7']}
    selected = sample_development(rows, split, 2)
    assert selected == sample_development(rows, split, 2)
    assert len(selected) == 2
    assert {r['conversation_id'] for r in selected} <= set(split['dev'])
    with pytest.raises(ValueError):
        development_ids({'dev': ['0'], 'test': ['0']})


def test_exact_vector_baseline_uses_cosine_not_length_or_gold():
    assert cosine_rank([1, 0], [[0, 9], [2, 0], [-1, 0], [1, 1]], 4) == [1, 3, 0, 2]
    with pytest.raises(ValueError):
        cosine_rank([0, 0], [[1, 0]], 1)
    with pytest.raises(ValueError):
        cosine_rank([1, 0], [[1]], 1)


def test_calibration_covers_errors_and_groups_and_is_reproducible():
    rows = [{'row_id': str(i), 'category': str(i % 3), 'system': str(i % 4),
             'judge_correct': i % 7 != 0} for i in range(600)]
    chosen = calibration_sample(rows)
    assert len(chosen) == len({r['row_id'] for r in chosen}) == 300
    assert chosen == calibration_sample(rows)
    strata = lambda rs: {(r['category'], r['system'], r['judge_correct']) for r in rs}
    assert strata(chosen) == strata(rows)
    with pytest.raises(ValueError):
        calibration_sample(rows[:20])
