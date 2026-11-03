"""Calibration math must preserve direction of overestimation and exclude invalids."""
import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    'owner_calibration', Path(__file__).resolve().parents[3] / 'scripts/calibrate-b0-owner.py')
assert spec and spec.loader
calibration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(calibration)


def test_directional_confusion_and_kappa():
    # Four judge positives: three correct and one overestimated answer.
    pairs = [(True, True)] * 3 + [(True, False)] + [(False, False)] * 4
    rows = [{'judge': a, 'human_correct': b} for a, b in pairs]
    value = calibration.simple(rows, 'judge')
    assert value['accuracy'] == 7 / 8
    assert value['kappa'] == pytest.approx(.75)
    assert value['false_positive_over_all'] == 1 / 8
    assert value['false_positive_over_judge_positive'] == 1 / 4
    assert value['confusion']['judge0_human1'] == 0


def test_invalid_is_not_a_wrong_answer_or_perfect_agreement():
    value = calibration.simple([
        {'judge': True, 'human_correct': True},
        {'judge': None, 'human_correct': False}], 'judge')
    assert value['n'] == value['invalid'] == 1
    assert value['accuracy'] == 1
    assert value['kappa'] is None
    assert value['adoptable_on_this_calibration'] is False


def test_three_repeat_change_denominator_excludes_incomplete_triplets():
    records = [{'model': 'test', 'row_id': row, 'repeat': i, 'correct': value}
               for row, values in [('a', [True, False, True]), ('b', [False, None, False])]
               for i, value in enumerate(values)]
    result = calibration.stability(records, [{'row_id': 'a'}, {'row_id': 'b'}], 'test')
    assert result['complete_rows'] == 1
    assert result['changed_any_of_three_ratio'] == 1
    assert result['pairwise_disagreement_n'] == 2
    assert result['pairwise_denominator'] == 3
    assert result['invalid_repeat_calls'] == 1
