"""A frozen new B0 must never inherit old exploratory correctness scores."""
import importlib.util
import json
from pathlib import Path

from agent_memory.evals.b0_frozen import AUTH


def test_current_controls_only_and_missing_is_explicit(tmp_path):
    script = Path(__file__).resolve().parents[3] / 'scripts/summarize-b0.py'
    spec = importlib.util.spec_from_file_location('frozen_summary', script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    historical = tmp_path / 'old.json'
    historical.write_text(json.dumps({'origin': 'old exploratory'}))
    config = {'frozen_b0_authorization': AUTH}
    assert module.controls_for_run(tmp_path, config, historical)['status'] == 'not_measured'
    current = tmp_path / 'correctness-observations.json'
    current.write_text(json.dumps({'origin': 'this new run'}))
    assert module.controls_for_run(tmp_path, config, historical)['origin'] == 'this new run'
    assert module.controls_for_run(tmp_path, {}, historical)['origin'] == 'old exploratory'
