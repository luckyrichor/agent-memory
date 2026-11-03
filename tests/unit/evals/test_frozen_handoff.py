"""A completed run must not overwrite a newer run or unrelated handoff text."""
import json
import subprocess
import sys
from pathlib import Path


def test_handoff_preserves_other_text_and_ignores_stale_runs(tmp_path):
    repo = tmp_path
    run = repo / '.local' / 'full-run'
    output = run / 'aggregate'
    output.mkdir(parents=True)
    current = repo / 'docs/evals/b0-current.json'
    current.parent.mkdir(parents=True)
    current.write_text(json.dumps({'baseline_configuration_id': 'fixed',
                                   'active_run': '.local/full-run'}))
    agents = repo / 'AGENTS.md'
    agents.write_text('# AGENTS.md\n\nKeep another author and instructions.\n')
    report = output / 'report.json'
    report.write_text(json.dumps({'run_manifest': {
        'config': {'baseline_configuration_id': 'fixed'}, 'harness_commit': 'fixture-unpublished',
        'harness_uncommitted_changes': True},
        'execution_status': {'status': 'paused_for_owner_calibration'},
        'measurements': {'fixture': {'rows': 24}}, 'flow_only': {'fixture': {'rows': 4}},
        'calibration_rows': 0}))
    script = Path(__file__).resolve().parents[3] / 'scripts/record-frozen-b0-handoff.py'
    command = [sys.executable, str(script), '--report', str(report), '--repo', str(repo)]
    subprocess.run(command, check=True, capture_output=True)
    assert 'Keep another author and instructions.' in agents.read_text()
    assert 'paused_for_owner_calibration' in agents.read_text()
    assert '已聚合实验行：28' in agents.read_text()
    progress = repo / 'docs/progress.md'
    subprocess.run(command, check=True, capture_output=True)
    assert progress.read_text().count('<!-- frozen-b0-closeout:') == 1
    saved = agents.read_text()
    current.write_text(json.dumps({'baseline_configuration_id': 'newer',
                                   'active_run': '.local/newer'}))
    subprocess.run(command, check=True, capture_output=True)
    assert agents.read_text() == saved
