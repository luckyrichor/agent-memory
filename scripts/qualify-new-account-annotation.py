"""Five repeated controls plus 100 distinct fictional full v3 samples, same real wire projection."""
import asyncio,json,os,time
from datetime import datetime,timezone
from pathlib import Path
import httpx
from agent_memory.evals.annotate import shared_sources
from agent_memory.evals.evidence_v3 import sha
from agent_memory.evals.model_policy import require_disabled_thinking
from agent_memory.evals.temporal import TemporalEvidenceBatch,check
from agent_memory.evals.temporal_preflight import virtual_item
ACCOUNT=os.environ['AGENT_MEMORY_LLM_ACCOUNT']
ARK=ACCOUNT=='ark-secondary'
ROOT=Path('.local/phase1/round3/new-accounts-v1/annotation-preflight')/ACCOUNT
PROMPT=Path('docs/evals/prompts/labeling-guide-v3-temporal-v1.txt')

async def qualify(model):
 out=ROOT/model.replace('/','-');out.mkdir(parents=True,exist_ok=True,mode=0o700)
 if (out/'report.json').exists():return json.loads((out/'report.json').read_text())
 rows=[];votes=[];next_request=0
 async with httpx.AsyncClient(timeout=150,trust_env=False) as client:
  for n in range(105):
   item=virtual_item(0 if n<5 else n-5)
   body={'model':model,'temperature':0,'thinking':{'type':'disabled'},'max_tokens':1536,
    'messages':[{'role':'system','content':PROMPT.read_text()},{'role':'user','content':json.dumps(shared_sources([item]),ensure_ascii=False)}]}
   saved=out/f'{n:03d}-result.json'
   if saved.exists():
    record=json.loads(saved.read_text());rows.append(record)
    if n<5 and record.get('decision'):votes.append(record['decision'])
    if not record.get('no_reasoning'):break
    continue
   (out/f'{n:03d}-request.json').write_text(json.dumps(body,ensure_ascii=False)+'\n')
   record={'number':n,'repeated':n<5,'attempts':[],'wire_sha256':sha(out/f'{n:03d}-request.json')}
   try:
    for attempt in range(3):
     await asyncio.sleep(max(0,next_request-time.monotonic()));next_request=time.monotonic()+3.1
     r=await client.post(('https://ark.cn-beijing.volces.com/api/v3' if ARK else os.environ['TENCENT_BASE_URL'].rstrip('/'))+'/chat/completions',json=body,headers={'Authorization':'Bearer '+os.environ['ARK_API_KEY' if ARK else 'TENCENT_API_KEY']})
     (out/f'{n:03d}-response-{attempt}-private.json').write_text(r.text);record['attempts'].append({'http':r.status_code})
     if r.status_code!=429:break
     if (r.json().get('error') or {}).get('code')=='SetLimitExceeded':break
     next_request=time.monotonic()+60
    record['http']=r.status_code
    if not r.is_success:
     record['error_code']=(r.json().get('error') or {}).get('code');raise RuntimeError('HTTP failed')
    d=r.json();record['usage']=d.get('usage');require_disabled_thinking(d);record['no_reasoning']=True
    if d['choices'][0].get('finish_reason') not in ('stop',None):raise ValueError('truncated')
    labels=TemporalEvidenceBatch.model_validate_json(d['choices'][0]['message']['content']).labels
    if len(labels)!=1 or labels[0].item_id!=item['item_id']:raise ValueError('ID coverage')
    checked=check(labels[0],item);record.update(format_valid=True,citation_valid=checked['citation_valid'],decision={'label':checked['label'],'temporal':labels[0].temporal})
    if n<5:votes.append(record['decision'])
   except Exception as exc:record['error_type']=type(exc).__name__
   rows.append(record);saved.write_text(json.dumps(record,indent=2)+'\n');(out/'progress.json').write_text(json.dumps(rows,indent=2)+'\n')
   if not record.get('no_reasoning'):break
  result={'model':model,'provider':'Ark' if ARK else 'TokenHub','account':ACCOUNT,'qualified_at':datetime.now(timezone.utc).isoformat(),'fictional_only':True,'schema':'full v3 plus temporal',
   'consistent_5':len(votes)==5 and all(v==votes[0] for v in votes),'format_n':sum(not r['repeated'] for r in rows),
   'format_valid':sum(bool(r.get('format_valid')) for r in rows if not r['repeated']),
   'distinct_inputs':len({r['wire_sha256'] for r in rows if not r['repeated']}),
   'observed_disabled_thinking':len(rows)==105 and all(r.get('no_reasoning') for r in rows),
   'calls':sum(len(r['attempts']) for r in rows),'reported_tokens':sum((r.get('usage') or {}).get('total_tokens',0) for r in rows),
   'prompt_sha256':sha(PROMPT),'temperature_requested':0}
  result['passed']=result['consistent_5'] and result['format_n']==result['distinct_inputs']==100 and result['format_valid']>=99 and result['observed_disabled_thinking']
  (out/'report.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result),flush=True);return result
if __name__=='__main__':
 import sys
 os.umask(0o077);asyncio.run(qualify(sys.argv[1]))
