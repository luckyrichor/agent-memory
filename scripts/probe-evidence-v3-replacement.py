import asyncio,json,os,time
from pathlib import Path
import httpx
from agent_memory.evals.model_policy import require_disabled_thinking
os.umask(0o077)
out=Path('.local/phase1/round3/evidence-v3-replacement-probes');out.mkdir(parents=True,exist_ok=True)
async def one(provider,model):
 saved=out/(provider+'-'+model+'.json')
 if saved.exists():
  print(json.dumps({**json.loads(saved.read_text()),'replayed_metadata':True}),flush=True)
  return
 token=os.environ['ARK_API_KEY'] if provider=='Ark' else os.environ['TENCENT_API_KEY']
 base='https://ark.cn-beijing.volces.com/api/v3' if provider=='Ark' else os.environ['TENCENT_BASE_URL'].rstrip('/')
 body={'model':model,'temperature':0,'max_tokens':256,'thinking':{'type':'disabled'},'response_format':{'type':'json_object'},'messages':[{'role':'system','content':'Return exactly this JSON object: {"label":"keep","reason":"supported"}. Do not reason.'},{'role':'user','content':'Synthetic availability test.'}]}
 record={'provider':provider,'model':model,'timestamp':time.time()}
 try:
  async with httpx.AsyncClient(timeout=75,trust_env=False) as c:
   r=await c.post(base+'/chat/completions',headers={'Authorization':'Bearer '+token},json=body)
   record['http']=r.status_code
   (out/(provider+'-'+model+'.raw.json')).write_text(r.text)
   if r.is_success:
    d=r.json();record['usage']=d.get('usage');record['returned_model']=d.get('model');require_disabled_thinking(d)
    record['format_ok']=json.loads(d['choices'][0]['message']['content'])=={'label':'keep','reason':'supported'}
   else:
    record['error_code']=r.json().get('error',{}).get('code')
 except Exception as e: record['error_type']=type(e).__name__
 (out/(provider+'-'+model+'.json')).write_text(json.dumps(record,indent=2))
 print(json.dumps(record),flush=True)
async def main():
 await asyncio.gather(one('Ark','deepseek-v4-pro-ga-260813'),one('TokenHub','hy4-preview'))
asyncio.run(main())
