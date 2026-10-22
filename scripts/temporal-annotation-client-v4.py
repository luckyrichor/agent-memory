"""Strict per-item rejection and genuine-response replay, without repairing provider output."""
import asyncio,hashlib,json,os,time
from datetime import datetime,timezone
from pathlib import Path
import httpx
from agent_memory.evals.annotate import shared_sources
from agent_memory.evals.evidence_v3 import sha,read_rows
from agent_memory.evals.model_policy import require_disabled_thinking
from agent_memory.evals.temporal import TemporalEvidenceBatch
from agent_memory.evals.temporal_output import validate_response,uncertain
BASE=Path('.local/phase1/round3/new-accounts-v1/increment-batches-v6')
# Replay only NEW account-round responses. Old incomplete batch4 is deliberately excluded.
INDEX={};LOCKS={};NEXT={}
FREEZE=Path('docs/evals/annotation-new-accounts-v1.json')
STRUCTURED_MODELS=set(json.loads(FREEZE.read_text()).get('structured_models',[])) if FREEZE.exists() else set()

def write(p,x):
 p.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
 temp=p.with_name(p.name+'.tmp');temp.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n');temp.replace(p)
def lines(p,rows):
 p.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
 p.write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows))
def request_hash(body):return hashlib.sha256(json.dumps(body,sort_keys=True).encode()).hexdigest()

def index_cache():
 if INDEX:return
 candidates=[]
 for request in sorted(BASE.glob('**/*-request.json')):
  if 'strict-output-v1' in request.parts:continue
  try:body=json.loads(request.read_text());h=request_hash(body)
  except (ValueError,OSError):continue
  prefix=request.name.removesuffix('-request.json')
  complete=(request.parent/f'{prefix}-checked.jsonl').exists()
  for response in sorted(request.parent.glob(prefix+'-response*.json')):
   candidates.append((h,response,0 if complete else 2))
 for ledger in sorted((BASE/'transport-retries').glob('*/ledger.json')):
  data=json.loads(ledger.read_text())
  for response in sorted(ledger.parent.glob('*-response-private.json')):
   candidates.append((data['request_sha256'],response,2))
 for h,path,rank in candidates:
  try:
   data=json.loads(path.read_text())
   if not isinstance(data.get('choices'),list) or not data['choices']:continue
   require_disabled_thinking(data)
   try:TemporalEvidenceBatch.model_validate_json(data['choices'][0]['message']['content']);rank=min(rank,1)
   except (ValueError,KeyError,TypeError):pass
  except (ValueError,KeyError,TypeError,RuntimeError):continue
  entry={'path':str(path),'sha256':sha(path),'rank':rank}
  if h not in INDEX or rank<INDEX[h]['rank']:INDEX[h]=entry
 write(BASE/'strict-output-v1/cache-index.json',INDEX)

async def post(client,body,token,base,entry,directory,offset):
 model=body['model'];LOCKS.setdefault(model,asyncio.Lock());response=None
 for attempt in range(3):
  async with LOCKS[model]:
   await asyncio.sleep(max(0,NEXT.get(model,0)-time.monotonic()));NEXT[model]=time.monotonic()+(3.1 if model=='hunyuan-turbos-vision-video-20250728' else 6.1)
  response=None
  try:
   response=await client.post(base+'/chat/completions',json=body,headers={'Authorization':'Bearer '+token})
   entry['attempts'].append({'http':response.status_code})
   (directory/f'{offset:04d}-response-{attempt}.json').write_text(response.text)
   entry['http']=response.status_code
   if response.is_success:return response.json()
   code=(response.json().get('error') or {}).get('code');entry['error_code']=code
   if response.status_code==402 or code in ('SetLimitExceeded','401010'):
    entry['quota_blocked']=True;return None
   if response.status_code not in (429,500,502,503,504):return None
   NEXT[model]=max(NEXT[model],time.monotonic()+60)
  except httpx.TransportError as exc:
   entry['attempts'].append({'error_type':type(exc).__name__});entry['error_type']=type(exc).__name__
   await asyncio.sleep(2**attempt)
 return None

async def side(out,model,rows,prompt,mode):
 assert mode=='annotation','this client is for new annotation only'
 INDEX.clear();index_cache();directory=out/model.replace('/','-');directory.mkdir(parents=True,exist_ok=True,mode=0o700)
 ledger_path=directory/'ledger.json';ledger=json.loads(ledger_path.read_text()) if ledger_path.exists() else []
 assert all(r['prompt_sha256']==sha(prompt) for r in ledger)
 if ledger and ledger[-1]['status']!='complete':return False
 if (directory/'COMPLETE').exists():
  assert (directory/'COMPLETE').read_text().strip()==sha(directory/'checked.jsonl')
  cached=read_rows(directory/'checked.jsonl');assert len(cached)==len(rows) and {r['item_id'] for r in cached}=={r['item_id'] for r in rows}
  return True
 done={r['offset'] for r in ledger}
 provider='Ark' if model=='glm-5-2-260617' else 'TokenHub'
 base='https://ark.cn-beijing.volces.com/api/v3' if provider=='Ark' else os.environ['TENCENT_BASE_URL'].rstrip('/')
 token=os.environ['ARK_API_KEY'] if provider=='Ark' else os.environ['TENCENT_API_KEY']
 async with httpx.AsyncClient(timeout=150,trust_env=False) as client:
  packet_size=1 if model=='hunyuan-turbos-vision-video-20250728' else 8
  for offset in range(0,len(rows),packet_size):
   if offset in done:continue
   aliases={f'i{i}':r for i,r in enumerate(rows[offset:offset+packet_size])}
   wire=[{**r,'item_id':key} for key,r in aliases.items()]
   assert all(set(r)=={'item_id','conversation_id','subject','source','candidate'} for r in wire)
   body={'model':model,'temperature':0,'thinking':{'type':'disabled'},'max_tokens':8192,
    'messages':[{'role':'system','content':prompt.read_text()},{'role':'user','content':json.dumps(shared_sources(wire),ensure_ascii=False)}]}
   if model=='hy4-preview':body['response_format']={'type':'json_object'}
   if model in STRUCTURED_MODELS:body['response_format']={'type':'json_schema','json_schema':{'name':'memory_labels','strict':True,'schema':TemporalEvidenceBatch.model_json_schema()}}
   h=request_hash(body);entry={'offset':offset,'items':len(aliases),'requested_model':model,'provider':provider,
    'timestamp':datetime.now(timezone.utc).isoformat(),'prompt_sha256':sha(prompt),'request_sha256':h,'status':'started','attempts':[],'packet_size':packet_size,'transport_version':'new-account-round-v1','account':'ark-secondary' if provider=='Ark' else 'tokenhub-secondary'}
   ledger.append(entry);write(ledger_path,ledger);write(directory/f'{offset:04d}-request.json',body)
   try:
    if h in INDEX:
     cached=INDEX[h];path=Path(cached['path']);assert sha(path)==cached['sha256']
     data=json.loads(path.read_text());entry.update(cache_hit=True,cache_path=str(path),cache_sha256=cached['sha256'],http=200)
     (directory/f'{offset:04d}-response-cached.json').write_text(path.read_text())
    else:
     entry['cache_hit']=False;data=await post(client,body,token,base,entry,directory,offset)
     if data is None:
      entry['status']='failed';write(ledger_path,ledger);return False
    require_disabled_thinking(data)
    entry['returned_model']=data.get('model')
    if entry['cache_hit']:entry['cached_original_usage']=data.get('usage')
    else:entry['usage']=data.get('usage')
    if data['choices'][0].get('finish_reason') not in ('stop',None):
     checked=[uncertain(item['item_id'],'response-truncated') for item in aliases.values()]
    else:checked=validate_response(data['choices'][0]['message']['content'],aliases)
    lines(directory/f'{offset:04d}-checked.jsonl',checked)
    entry.update(status='complete',schema_invalid=sum(not r['schema_valid'] for r in checked),citation_invalid=sum(not r['citation_valid'] for r in checked))
   except Exception as exc:
    entry.update(status='failed',error_type=type(exc).__name__);write(ledger_path,ledger);return False
   write(ledger_path,ledger)
   print(json.dumps({'model':model,'stage':str(out),'completed':offset+len(aliases),'total':len(rows),'cache_hit':entry['cache_hit'],'schema_invalid':entry['schema_invalid']}),flush=True)
 checked=[r for p in sorted(directory.glob('*-checked.jsonl')) for r in read_rows(p)]
 assert len(checked)==len(rows) and {r['item_id'] for r in checked}=={r['item_id'] for r in rows}
 lines(directory/'checked.jsonl',checked);lines(directory/'labels.jsonl',[{k:r[k] for k in ('item_id','label','reason')} for r in checked])
 (directory/'COMPLETE').write_text(sha(directory/'checked.jsonl')+'\n');return True
