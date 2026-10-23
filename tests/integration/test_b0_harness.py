"""Regression: real API/embedding worker, no external model traffic."""
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4


def test_unfiltered_baseline_and_worker_pipeline_offline():
    repo = Path(__file__).resolve().parents[2]
    root = repo / '.local' / 'phase2' / 'b0' / ('regression-' + uuid4().hex)
    root.mkdir(parents=True)
    dataset = root / 'fixture-dev.jsonl'
    dataset.write_text(json.dumps({
        'conversation_id': 'fixture-dev',
        'documents': [
            {'source_id': 'normal', 'session_id': 'fixture-dev', 'role': 'user',
             'text': 'Synthetic harmless console preference.'},
            {'source_id': 'rejected', 'session_id': 'fixture-dev', 'role': 'user',
             'text': 'Contact alice@example.test'},
        ],
        'questions': [{'question_id': 'fixture-q', 'text': 'Synthetic fixture question?',
                       'answer': 'fixture answer', 'category': 'fixture', 'relevant': {'normal': 1},
                       'evidence_available': True, 'abstention': False}],
        'metadata': {'evidence_level': 'turn'},
    }) + '\n')
    manifest = root / 'manifest.json'
    manifest.write_text(json.dumps({'offline-fixture': {
        'path': str(dataset), 'sha256': hashlib.sha256(dataset.read_bytes()).hexdigest(),
        'data_level': 'C synthetic offline harness regression only',
    }}))
    config = root / 'config.json'
    config.write_text(json.dumps({'seed': 42, 'offline_fixture': True,
                                  'datasets_manifest': str(manifest),
                                  'conversations_per_dataset': {'offline-fixture': 1},
                                  'questions_per_conversation': 1, 'system_context_budget': 2000}))
    env = {k: v for k, v in os.environ.items()
           if k not in {'ARK_API_KEY', 'TENCENT_API_KEY', 'TOKENHUB_API_KEY'}}
    result = subprocess.run([
        sys.executable, 'scripts/run-b0.py', '--dataset', 'offline-fixture', '--mode', 'both',
        '--config', str(config), '--metrics', 'RT,E', '--output', str(root / 'run'),
    ], cwd=repo, env=env, capture_output=True, text=True, timeout=120, check=False)
    assert result.returncode == 0, result.stderr[-2000:]
    status = json.loads((root / 'run/status.json').read_text())
    assert status['status'] == 'offline_fixture_completed'
    assert status['model_attempts'] == 0
    imports = [json.loads(line) for line in (root / 'run/imports-private.jsonl').open()]
    direct = [r for r in imports if r['mode'] == 'direct']
    assert len(direct) == 3
    assert all(r['naive_corpus_count'] == 2 and r['memories'] == 1 for r in direct)
    assert all(len(r['rejected']) == 1 for r in direct)
    assert all(any(j['outcome'] == 'succeeded' for j in r['embedding_outcomes']) for r in direct)
    usage = [json.loads(line) for line in (root / 'run/usage.jsonl').open()]
    assert usage and all(r.get('fixture_only') and not r.get('new_http_call') for r in usage)
    assert not (root / 'run/calibration-300-private.csv').exists()
