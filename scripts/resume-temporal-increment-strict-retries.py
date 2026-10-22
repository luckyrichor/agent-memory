"""Resume frozen cohort with repaired rate-limited preflight and paced transport only."""
import asyncio,hashlib,importlib.util,json,os,time,uuid
from datetime import datetime,timezone
from collections import defaultdict
from pathlib import Path
import httpx
from agent_memory.evals.evidence_v3 import sha
from agent_memory.evals.temporal import TemporalEvidenceBatch
from agent_memory.evals.model_policy import require_disabled_thinking

def module(path,name):
 spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

async def main():
 engine=module('scripts/run-temporal-increment.py','frozen_increment')
 original_module=engine.module
 class Qualification:
  async def qualify(self,model):
   repaired=Path('.local/phase1/round3/tokenhub-pool-qualification-throttled-v1')/model.replace('/','-')/'report.json'
   if repaired.exists():return json.loads(repaired.read_text())
   old=original_module('scripts/qualify-tokenhub-pool-model.py','legacy_qualification')
   return await old.qualify(model)
 def imported(path,name):
  if path=='scripts/qualify-tokenhub-pool-model.py':return Qualification()
  return original_module(path,name)
 engine.module=imported
 original_post=httpx.AsyncClient.post
 locks=defaultdict(asyncio.Lock);next_start={}
 async def paced_post(client,url,**kwargs):
  model=kwargs.get('json',{}).get('model','unknown')
  async with locks[model]:
   await asyncio.sleep(max(0,next_start.get(model,0)-time.monotonic()))
   next_start[model]=time.monotonic()+6.1
  body=kwargs.get('json',{})
  strict_annotation='temporal' in body.get('messages',[{}])[0].get('content','')
  record={'model':model,'created_at':datetime.now(timezone.utc).isoformat(),
   'request_sha256':hashlib.sha256(json.dumps(body,sort_keys=True).encode()).hexdigest(),'attempts':[]}
  trace=engine.e.ROOT/'transport-retries'/uuid.uuid4().hex;trace.mkdir(parents=True,mode=0o700)
  for attempt in range(3):
   try:
    response=await original_post(client,url,**kwargs)
    event={'http':response.status_code};record['attempts'].append(event)
    (trace/f'{attempt}-response-private.json').write_text(response.text)
    if response.is_success and strict_annotation:
     data=response.json();event['usage']=data.get('usage');require_disabled_thinking(data)
     if data['choices'][0].get('finish_reason') not in ('stop',None):raise ValueError('truncated response')
     parsed=TemporalEvidenceBatch.model_validate_json(data['choices'][0]['message']['content'])
     inputs=json.loads(body['messages'][1]['content'])['items']
     expected={x['item_id'] for x in inputs}
     if len(parsed.labels)!=len(expected) or {x.item_id for x in parsed.labels}!=expected:raise ValueError('coverage mismatch')
    event['accepted_by_transport']=True
    break
   except (httpx.TransportError,ValueError) as exc:
    if not record['attempts'] or record['attempts'][-1].get('error_type'):
     record['attempts'].append({})
    record['attempts'][-1]['error_type']=type(exc).__name__
    (trace/'ledger.json').write_text(json.dumps(record,indent=2)+'\n')
    if attempt==2:raise
    await asyncio.sleep(6.1)
  (trace/'ledger.json').write_text(json.dumps(record,indent=2)+'\n')
  if response.status_code==429:
   try:code=(response.json().get('error') or {}).get('code')
   except Exception:code=None
   if code!='SetLimitExceeded':
    next_start[model]=max(next_start.get(model,0),time.monotonic()+60)
  return response
 httpx.AsyncClient.post=paced_post
 root=engine.e.ROOT
 (root/'strict-retry-resume-context.json').write_text(json.dumps({'launcher_sha256':sha(Path(__file__)),
  'frozen_driver_sha256':sha(Path('scripts/run-temporal-increment.py')),
  'change':'transport pacing only; original candidate/prompt/quote validator unchanged; repaired preflight retries ordinary429 only; whole changed side across all selected batches relabeled',
  'format_or_network_retry_limit':2,'no_field_removal_or_output_repair':True,'minimum_seconds_between_same_model_requests':6.1,'ordinary_429_cooldown_seconds':60},indent=2)+'\n')
 await engine.main()

if __name__=='__main__':
 os.umask(0o077);asyncio.run(main())
