"""Do not count metadata/headers as text or call incomplete deletion a pass."""
import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    'b0_evidence', Path(__file__).resolve().parents[3] / 'scripts/supplement-b0-evidence.py')
assert spec and spec.loader
evidence = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evidence)


def test_egress_text_counts_payload_only():
    body = {'model': 'not-text', 'headers': {'Authorization': 'not-text'},
            'messages': [{'content': '你好'}, {'content': [{'type': 'text', 'text': 'ok'},
                {'type': 'image_url', 'image_url': 'not-text'}]}], 'input': ['a', 'b']}
    parts = evidence.strings(body)
    assert parts == ['你好', 'ok', 'a', 'b']
    assert sum(len(s.encode('utf-8')) for s in parts) == 10


def test_recovery_lineage_deduplicates_ancestor_and_rejects_exploration(tmp_path):
    a, b = tmp_path / 'a', tmp_path / 'b'
    for root, parents in [(a, []), (b, [str(a), str(a)])]:
        root.mkdir()
        (root / 'run-manifest.json').write_text(json.dumps({
            'baseline_commit': '1e9d6f3b25b58c85792344000d7e1b5a71a79737',
            'config': {'baseline_configuration_id': 'B0-deepseek-v4-pro-kinfra-20261026-v1',
                       'resume_roots': parents}}))
    assert evidence.lineage(b) == [b.resolve(), a.resolve()]
    d = json.loads((a / 'run-manifest.json').read_text())
    d['config']['baseline_configuration_id'] = 'exploratory'
    (a / 'run-manifest.json').write_text(json.dumps(d))
    with pytest.raises(AssertionError):
        evidence.lineage(b)


def test_deletion_observation_stays_partial():
    result = evidence.controls_index({'observations': [
        {'id': 'LC7', 'retained_body_versions': 1, 'scale': 1}]})
    assert result['LC7']['status'].startswith('partial')
    assert result['LC7']['retained_body_versions_per_repeat'] == [1]
