"""Resume frozen cohort with repaired rate-limited preflight and paced transport only."""
import asyncio,importlib.util,json,os,time
from collections import defaultdict
from pathlib import Path
import httpx
from agent_memory.evals.evidence_v3 import sha

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
  response=await original_post(client,url,**kwargs)
  if response.status_code==429:
   try:code=(response.json().get('error') or {}).get('code')
   except Exception:code=None
   if code!='SetLimitExceeded':
    next_start[model]=max(next_start.get(model,0),time.monotonic()+60)
  return response
 httpx.AsyncClient.post=paced_post
 root=engine.e.ROOT
 (root/'throttled-resume-context.json').write_text(json.dumps({'launcher_sha256':sha(Path(__file__)),
  'frozen_driver_sha256':sha(Path('scripts/run-temporal-increment.py')),
  'change':'transport pacing only; original candidate/prompt/quote validator unchanged; repaired preflight retries ordinary429 only; whole changed side across all selected batches relabeled',
  'minimum_seconds_between_same_model_requests':6.1,'ordinary_429_cooldown_seconds':60},indent=2)+'\n')
 await engine.main()

if __name__=='__main__':
 os.umask(0o077);asyncio.run(main())
