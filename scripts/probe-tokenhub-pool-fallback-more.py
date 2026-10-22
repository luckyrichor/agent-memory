"""Tiny availability probes for owner-authorized TokenHub substitutions; no balances."""
import asyncio,json,os,time
from pathlib import Path
import httpx
from agent_memory.evals.model_policy import require_disabled_thinking
ROOT=Path('.local/phase1/round3/tokenhub-pool-fallback-probes')
MODELS=('glm-5.2','mimo-v2.5-pro','minimax-m3','deepseek-v4.1-flash-1017','deepseek-v4-flash-202605')
async def one(model):
 p=ROOT/(model+'.json')
 if p.exists():print(p.read_text());return
 body={'model':model,'temperature':0,'max_tokens':256,'thinking':{'type':'disabled'},'response_format':{'type':'json_object'},'messages':[{'role':'system','content':'Return exactly {"label":"keep","reason":"supported"}. No explanation.'},{'role':'user','content':'Fictitious availability test.'}]}
 r={'model':model,'provider':'TokenHub','timestamp':time.time()}
 try:
  async with httpx.AsyncClient(timeout=90,trust_env=False) as c:
   response=await c.post(os.environ['TENCENT_BASE_URL'].rstrip('/')+'/chat/completions',headers={'Authorization':'Bearer '+os.environ['TENCENT_API_KEY']},json=body)
   r['http']=response.status_code;(ROOT/(model+'-response-private.json')).write_text(response.text)
   d=response.json()
   if response.is_success:
    r['usage']=d.get('usage');r['returned_model']=d.get('model');require_disabled_thinking(d)
    r['valid']=json.loads(d['choices'][0]['message']['content'])=={'label':'keep','reason':'supported'}
   else:r['error_code']=(d.get('error') or {}).get('code')
 except Exception as e:r['error_type']=type(e).__name__
 p.write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r),flush=True)
async def main():await asyncio.gather(*(one(m) for m in MODELS))
if __name__=='__main__':
 os.umask(0o077);ROOT.mkdir(parents=True,exist_ok=True,mode=0o700);asyncio.run(main())
