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
    controls = json.loads((root / 'run/correctness-observations.json').read_text())
    filtering = [r for r in controls['observations'] if r['id'] in ('LC4', 'RT10')]
    assert len(filtering) == 6 and all(r['setup_valid'] for r in filtering)
    resumed_config = root / 'resumed-config.json'
    resumed_config.write_text(json.dumps({**json.loads(config.read_text()),
                                         'resume_roots': [str(root / 'run')]}))
    resumed = subprocess.run([
        sys.executable, 'scripts/run-b0.py', '--dataset', 'offline-fixture', '--mode', 'both',
        '--config', str(resumed_config), '--metrics', 'RT,E', '--output', str(root / 'resumed'),
    ], cwd=repo, env=env, capture_output=True, text=True, timeout=120, check=False)
    assert resumed.returncode == 0, resumed.stderr[-2000:]
    resumed_status = json.loads((root / 'resumed/status.json').read_text())
    assert resumed_status['status'] == 'offline_fixture_completed'
    assert resumed_status['model_records_including_replays'] == 0
    assert {r['row_id']: r for r in json.loads(
        (root / 'resumed/graded-results-private.json').read_text())} == {
            r['row_id']: r for r in json.loads((root / 'run/graded-results-private.json').read_text())}
    provenance = [json.loads(line) for line in (root / 'resumed/resumed-datasets.jsonl').open()]
    assert len(provenance) == 1 and not provenance[0]['database_state_restored']



def test_full_history_truncates_only_on_context_length_rejection(tmp_path):
    repo = Path(__file__).resolve().parents[2]
    config = tmp_path / "fixture.json"
    config.write_text(json.dumps({"offline_fixture": True}))
    program = r"""
import asyncio, importlib.util, copy
spec=importlib.util.spec_from_file_location('driver','scripts/run-b0.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class Stub:
 def __init__(self,error):self.error=error;self.bodies=[]
 async def request(self,role,body,**kwargs):
  self.bodies.append(copy.deepcopy(body))
  if len(self.bodies)==1:return {'error':{'message':self.error}}
  return {'model':'fixture','choices':[{'message':{'content':'ok'}}]}
async def run():
 context=[{'text':'old'}, {'text':'recent'}]
 stub=Stub('Maximum context length exceeded')
 answer,data=await m.ModelIO.answer(stub,'question',context,full_history=True)
 assert answer=='ok' and len(stub.bodies)==2
 assert data['_b0_full_context_truncation']['truncated']
 assert 'recent' in stub.bodies[-1]['messages'][1]['content']
 assert 'old' not in stub.bodies[-1]['messages'][1]['content']
 stub=Stub('Unsupported response format')
 answer,data=await m.ModelIO.answer(stub,'question',context,full_history=True)
 assert answer is None and len(stub.bodies)==1
 assert not data['_b0_full_context_truncation']['truncated']
asyncio.run(run())
"""
    subprocess.run([sys.executable, '-c', program, '--config', str(config)],
                   cwd=repo, check=True, capture_output=True, text=True, timeout=30)
