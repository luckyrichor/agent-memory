"""Bounded owner-authorized quota fallback. Whole changed side; no billing mutations."""
import asyncio
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

CANDIDATES=('deepseek-v4.1-flash-1017','deepseek-v4-flash-202605','deepseek/deepseek-flash')
BASE=Path('.local/phase1/round3/tokenhub-pool-v4')
RUNNER='scripts/run-tokenhub-pool-fallback.py'

def quota_blocked(root):
 for path in root.glob('pool-shard-*/**/ledger.json'):
  rows=json.loads(path.read_text())
  if not rows or rows[-1]['status']=='complete':continue
  last=rows[-1]
  response=path.parent/f"{last['offset']:04d}-response.json"
  error=json.loads(response.read_text()).get('error',{}) if response.exists() else {}
  if last.get('http_status')==402:return True
  if last.get('http_status')==429 and error.get('code')=='SetLimitExceeded':return True
 return False

def execute(action, model):
 return subprocess.run([sys.executable,RUNNER,action,'--model',model],check=False).returncode

async def main():
 spec=importlib.util.spec_from_file_location('pool_qualification','scripts/qualify-tokenhub-pool-model.py')
 qualification=importlib.util.module_from_spec(spec);spec.loader.exec_module(qualification)
 for model in CANDIDATES:
  root=BASE/model.replace('/','-')
  if (root/'audit72'/'manifest.json').exists():
   print(json.dumps({'model':model,'audit_already_frozen':True}));return
  result=await qualification.qualify(model)
  if not result['passed']:continue
  if not (root/'manifest.json').exists() and execute('prepare',model):raise RuntimeError('replacement preparation failed')
  if not (root/'SCHEMA_COMPLETE').exists() and execute('schema',model):
   raise RuntimeError('protocol format failure; do not lower qualification')
  if not execute('run',model):return
  if not quota_blocked(root):raise RuntimeError('nonquota failure retained; no automatic semantic or validator changes')
  print(json.dumps({'retired_partial_model':model,'reason':'quota','next_model_entire_side':True}),flush=True)
 raise RuntimeError('qualified available candidate list exhausted; preserve all progress')

if __name__=='__main__':
 os.umask(0o077);asyncio.run(main())
