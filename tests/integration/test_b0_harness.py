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


    # Simulate a quota/interruption after completed direct units, before a complete table.
    import shutil

    partial = root / 'partial'
    shutil.copytree(root / 'run', partial)
    for table in partial.glob('table-*-private.json'):
        table.unlink()
    (partial / 'graded-results-private.json').unlink()
    for filename in ('results-private.jsonl', 'imports-private.jsonl'):
        records = [json.loads(line) for line in (partial / filename).read_text().splitlines()]
        (partial / filename).write_text(''.join(json.dumps(r) + '\n'
                                               for r in records if r['mode'] == 'direct'))
    resumed_config.write_text(json.dumps({**json.loads(config.read_text()),
                                         'resume_roots': [str(partial)]}))
    continuation = subprocess.run([
        sys.executable, 'scripts/run-b0.py', '--dataset', 'offline-fixture', '--mode', 'both',
        '--config', str(resumed_config), '--metrics', 'RT,E', '--output', str(root / 'partial-resumed'),
    ], cwd=repo, env=env, capture_output=True, text=True, timeout=120, check=False)
    assert continuation.returncode == 0, continuation.stderr[-2000:]
    units = [json.loads(line) for line in
             (root / 'partial-resumed/resumed-conversations.jsonl').read_text().splitlines()]
    assert len(units) == 3 and all(r['mode'] == 'direct' for r in units)
    continued = json.loads((root / 'partial-resumed/graded-results-private.json').read_text())
    assert len(continued) == 24 and len({r['row_id'] for r in continued}) == 24
    assert all(r['answer_valid'] for r in continued)
    stage_replays = [json.loads(line) for line in (root / 'partial-resumed/resumed-stages-private.jsonl').read_text().splitlines()]
    assert stage_replays and all(r['new_answer_calls'] == 0 and r['origin']['sha256'] for r in stage_replays)



def test_full_history_truncates_only_on_context_length_rejection(tmp_path):
    repo = Path(__file__).resolve().parents[2]
    config = tmp_path / "fixture.json"
    config.write_text(json.dumps({"offline_fixture": True}))
    program = r"""
import asyncio, importlib.util, copy
spec=importlib.util.spec_from_file_location('driver','scripts/run-b0.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class Stub:
 def __init__(self,error):self.error=error;self.bodies=[];self.config={}
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


def test_four_key_routing_never_serializes_credentials(tmp_path):
    repo = Path(__file__).resolve().parents[2]
    config = tmp_path / 'fixture-source.json'
    config.write_text(json.dumps({'offline_fixture': True}))
    program = r"""
import asyncio, importlib.util, json, sys
from pathlib import Path
sys.path.insert(0,'scripts')
import b0_accounts
spec=importlib.util.spec_from_file_location('driver','scripts/run-b0.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
root=Path(sys.argv[1]);secret='fictional-private-credential-for-mock-only'
def fake(account):
 return b0_accounts.ACCOUNTS[account][0],'https://fixture.invalid',secret
b0_accounts.credential=fake
async def run():
 for account,(provider,*_) in b0_accounts.ACCOUNTS.items():
  calls=[]
  def respond(request):
   calls.append(request.headers['Authorization'])
   return m.httpx.Response(200,json={'model':'fictional','choices':[{'message':{'content':'ok'}}]})
  io=m.ModelIO(root/account,config={'role_accounts':{'extraction':{provider:account}}})
  io.clients[id(asyncio.get_running_loop())]=m.httpx.AsyncClient(transport=m.httpx.MockTransport(respond))
  await io.request('extraction',{'model':'fictional','messages':[]},provider=provider)
  assert calls==['Bearer '+secret] and io.calls[0]['account']==account
  for path in (root/account).rglob('*.json*'):assert secret not in path.read_text()
  for client in io.clients.values():await client.aclose()
 def overdue(request):return m.httpx.Response(403,json={'error':{'code':'AccountOverdueError'}})
 io=m.ModelIO(root/'overdue',config={})
 io.clients[id(asyncio.get_running_loop())]=m.httpx.AsyncClient(transport=m.httpx.MockTransport(overdue))
 for _ in range(2):
  try:await io.embedding('Fictional quota regression')
  except RuntimeError as error:assert str(error)=='RUNTIME_QUOTA_PAUSED'
  else:raise AssertionError('overdue embedding must pause for rotation')
 assert len(io.calls)==1 and io.runtime_blocked
 assert json.loads((root/'overdue/runtime-quota-pause.json').read_text())['error_code']=='AccountOverdueError'
 for client in io.clients.values():await client.aclose()
 io=m.ModelIO(root/'openai-fixture',fixture=True,config={'embedding_model':'fictional-1024','embedding_provider':'TokenHub','embedding_protocol':'openai'})
 vector=await io.embedding('Fictional embedding fixture')
 assert len(vector)==1024 and io.calls[0]['fixture_only'] and not io.calls[0]['new_http_call']
 body=json.loads((root/'openai-fixture/calls/0000001-request-private.json').read_text())
 assert isinstance(body['input'],str) and body['dimensions']==1024
 for client in io.clients.values():await client.aclose()
asyncio.run(run())
"""
    subprocess.run([sys.executable, '-c', program, str(tmp_path / 'ledger'), '--config', str(config)],
                   cwd=repo, check=True, capture_output=True, text=True, timeout=30)
