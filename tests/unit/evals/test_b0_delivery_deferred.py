"""Owner-requested aggregate deferral survives measurement subprocess closeout."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    'managed_b0', Path(__file__).resolve().parents[3] / 'scripts/managed-b0-execution.py')
assert spec and spec.loader
managed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(managed)


def test_defer_until_explicit_completeness_check():
    state = {'aggregate_delivery_request': {'status': 'deferred_until_complete'}}
    assert managed.aggregate_delivery_deferred(state)
    assert managed.aggregate_delivery_deferred({**state, 'calibration_exported': True})
    assert managed.aggregate_delivery_deferred({**state, 'phase2_accepted': True})
    assert not managed.aggregate_delivery_deferred({**state, 'full_aggregate_ready': True})
    assert not managed.aggregate_delivery_deferred({})
