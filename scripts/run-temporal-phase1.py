"""Owner-approved long-term screening and separately frozen incremental batches."""
import argparse, asyncio, hashlib, importlib.util, json, os, random, subprocess, zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
import httpx
from agent_memory.evals.annotate import shared_sources
from agent_memory.evals.evidence_v3 import read_rows, sha
from agent_memory.evals.human_review import answers
from agent_memory.evals.metrics import ratio
from agent_memory.evals.model_policy import require_disabled_thinking
from agent_memory.evals.temporal import TemporalBatch, TemporalEvidenceBatch, check

ROOT=Path('.local/phase1/round3/temporal-v1')
PRIOR=Path('.local/phase1/round3/tokenhub-pool-v4/deepseek-v4.1-flash-1017')
MODELS=('deepseek-v4.1-flash-1017','hy4-preview')

def write(p,x):
 p.parent.mkdir(parents=True,exist_ok=True,mode=0o700);p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n')
def lines(p,x):
 p.parent.mkdir(parents=True,exist_ok=True,mode=0o700);p.write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in x))
def load(p):return json.loads(p.read_text())

def prepare():
 out=ROOT/'screen';out.mkdir(parents=True,exist_ok=True,mode=0o700)
 if (out/'manifest.json').exists():return
 # Human return was finalized against immutable pack before any model calls.
 score=load(ROOT/'owner-final/report.json');assert score['passed']
 checked=answers(PRIOR/'audit72/audit-blind.jsonl',Path('.local/dulemon72-v3-final-20261022.csv'))
 mapping=load(PRIOR/'audit72/opaque-map-private.json')
 human={mapping[k]:v.model_copy(update={'item_id':mapping[k]}).model_dump() for k,v in checked.items()}
 old={r['item_id']:r for r in read_rows(Path('.local/phase1/round3/verbatim-filter/run-final/human-confirmed-labels.jsonl'))}
 assert not human.keys()&old.keys()
 merged=old|human
 allitems={r['item_id']:r for r in read_rows(Path('.local/phase1/chinese-expansion-v2/dulemon/items.jsonl'))}
 items={r['item_id']:r for r in read_rows(PRIOR/'pool-items.jsonl')}
 left={r['item_id']:r for r in read_rows(PRIOR/'replacement-complete-labels.jsonl')}
 right={r['item_id']:r for r in read_rows(PRIOR/'hy4-complete-labels.jsonl')}
 joint={k for k in items if left[k]['label']==right[k]['label']=='keep'}
 pool=joint-old.keys();assert len(pool)==265
 positive={k for k in merged if merged[k]['label']=='keep'}
 rejected={k for k in human if human[k]['label']!='keep'}
 assert len(rejected)==3 and all('临时' in human[k]['reason'] for k in rejected)
 groups=defaultdict(list)
 for k,v in human.items():groups[allitems[k]['conversation_id']].append(v['label']=='keep')
 estimate=ratio([(sum(v),len(v)) for _,v in sorted(groups.items())]).to_dict()
 lines(ROOT/'human-all-original.jsonl',[merged[k] for k in sorted(merged)])
 lines(ROOT/'human-positive-labels.jsonl',[merged[k] for k in sorted(positive)])
 lines(ROOT/'human-positive-items.jsonl',[allitems[k] for k in sorted(positive)])
 wanted=pool|positive
 lines(out/'items.jsonl',[allitems[k] for k in sorted(wanted)])
 write(out/'manifest.json',{'created_at':datetime.now(timezone.utc).isoformat(),'models':MODELS,
  'pool_ids':sorted(pool),'human_positive_ids':sorted(positive),'new_human_rejected_ids':sorted(rejected),
  'items':len(wanted),'pool':len(pool),'old_positive':sum(x['label']=='keep' for x in old.values()),
  'new_positive':sum(x['label']=='keep' for x in human.values()),'deduplicated_human_positive':len(positive),
  'audit_precision':estimate,'audit_errors':len(rejected),'maximum_errors':3,'audit_passed_at_boundary':True,
  'error_types':{'temporary-state-as-long-term':len(rejected)},'adoption_requires_owner_decision':True,
  'prompt_sha256':sha(Path('docs/evals/prompts/temporal-filter-v1.txt')),
  'items_sha256':sha(out/'items.jsonl'),'plan_sha256':sha(Path('docs/plans/2026-10-22-agent-memory-interview-plan-v3.md'))})
 print(json.dumps({k:load(out/'manifest.json')[k] for k in ('items','pool','deduplicated_human_positive','audit_precision')}))

async def side(out,model,rows,prompt,mode):
 directory=out/model.replace('/','-');directory.mkdir(parents=True,exist_ok=True,mode=0o700)
 if (directory/'COMPLETE').exists():
  assert (directory/'COMPLETE').read_text().strip()==sha(directory/'checked.jsonl')
  cached=read_rows(directory/'checked.jsonl')
  assert len(cached)==len(rows) and {r['item_id'] for r in cached}=={r['item_id'] for r in rows}
  assert all(r['prompt_sha256']==sha(prompt) for r in load(directory/'ledger.json'))
  return True
 ledger=load(directory/'ledger.json') if (directory/'ledger.json').exists() else []
 if ledger and ledger[-1]['status']!='complete':return False
 assert all(r['prompt_sha256']==sha(prompt) for r in ledger)
 done={r['offset'] for r in ledger}
 provider='Ark' if model=='glm-5-2-260617' else 'TokenHub'
 base='https://ark.cn-beijing.volces.com/api/v3' if provider=='Ark' else os.environ['TENCENT_BASE_URL'].rstrip('/')
 token=os.environ['ARK_API_KEY'] if provider=='Ark' else os.environ['TENCENT_API_KEY']
 async with httpx.AsyncClient(timeout=150,trust_env=False) as client:
  for offset in range(0,len(rows),8):
   if offset in done:continue
   batch=rows[offset:offset+8];aliases={f'i{j}':r for j,r in enumerate(batch)}
   wire=[{**r,'item_id':k} for k,r in aliases.items()]
   assert all(set(r)=={'item_id','conversation_id','subject','candidate','source'} for r in wire)
   body={'model':model,'temperature':0,'thinking':{'type':'disabled'},'max_tokens':8192 if mode=='annotation' else 1024,
    'messages':[{'role':'system','content':prompt.read_text()},{'role':'user','content':json.dumps(shared_sources(wire),ensure_ascii=False)}]}
   if model=='hy4-preview':body['response_format']={'type':'json_object'}
   entry={'offset':offset,'items':len(batch),'requested_model':model,'provider':provider,'status':'started',
    'timestamp':datetime.now(timezone.utc).isoformat(),'prompt_sha256':sha(prompt),
    'request_sha256':hashlib.sha256(json.dumps(body,sort_keys=True).encode()).hexdigest(),'attempts':[]}
   ledger.append(entry);write(directory/'ledger.json',ledger);write(directory/f'{offset:04d}-request.json',body)
   try:
    for attempt in range(3):
     response=await client.post(base+'/chat/completions',json=body,
      headers={'Authorization':'Bearer '+token})
     (directory/f'{offset:04d}-response-{attempt}.json').write_text(response.text)
     entry['attempts'].append({'http':response.status_code})
     if response.is_success:break
     error=(response.json().get('error') or {}).get('code');entry['error_code']=error
     if response.status_code==402 or str(error) in ('SetLimitExceeded','401010'):
      entry['quota_blocked']=True;break
     if response.status_code not in (429,500,502,503,504):break
     await asyncio.sleep(2**attempt)
    entry['http']=response.status_code
    if not response.is_success:raise RuntimeError('HTTP-failed')
    data=response.json();entry['usage']=data.get('usage');entry['returned_model']=data.get('model');require_disabled_thinking(data)
    if data['choices'][0].get('finish_reason') not in ('stop',None):raise ValueError('truncated')
    schema=TemporalBatch if mode=='screen' else TemporalEvidenceBatch
    parsed=schema.model_validate_json(data['choices'][0]['message']['content'])
    if len(parsed.labels)!=len(aliases) or {x.item_id for x in parsed.labels}!=set(aliases):raise ValueError('ID coverage')
    results=[];proofs=[]
    for x in parsed.labels:
     item=aliases[x.item_id];x=x.model_copy(update={'item_id':item['item_id']})
     results.append(x.model_dump() if mode=='screen' else check(x,item));proofs.append(x.model_dump())
    lines(directory/f'{offset:04d}-checked.jsonl',results);lines(directory/f'{offset:04d}-proofs.jsonl',proofs)
    entry['status']='complete'
   except Exception as exc:
    entry.update(status='failed',error_type=type(exc).__name__);write(directory/'ledger.json',ledger)
    print(json.dumps({'model':model,'stage':str(out),'offset':offset,'failed':entry['error_type'],'http':entry.get('http')}),flush=True);return False
   write(directory/'ledger.json',ledger)
   print(json.dumps({'model':model,'stage':str(out),'complete':offset+len(batch),'total':len(rows)}),flush=True)
  checked=[r for p in sorted(directory.glob('*-checked.jsonl')) for r in read_rows(p)]
  assert len(checked)==len(rows) and {r['item_id'] for r in checked}=={r['item_id'] for r in rows}
  lines(directory/'checked.jsonl',checked);(directory/'COMPLETE').write_text(sha(directory/'checked.jsonl')+'\n')
 return True

async def run_screen():
 prepare();out=ROOT/'screen';m=load(out/'manifest.json');prompt=Path('docs/evals/prompts/temporal-filter-v1.txt')
 assert sha(prompt)==m['prompt_sha256'] and sha(out/'items.jsonl')==m['items_sha256']
 rows=read_rows(out/'items.jsonl')
 result=await asyncio.gather(*(side(out,model,rows,prompt,'screen') for model in MODELS))
 if not all(result):raise RuntimeError('preserved incomplete full side; no mixed adoption')
 summarize_screen()

def summarize_screen():
 out=ROOT/'screen';m=load(out/'manifest.json');sets=[]
 for model in m.get('active_models',MODELS):
  directory=out/model;assert (directory/'COMPLETE').read_text().strip()==sha(directory/'checked.jsonl')
  sets.append({r['item_id'] for r in read_rows(directory/'checked.jsonl') if r['temporal']=='临时'})
 removed=sets[0]|sets[1];pool=set(m['pool_ids']);positives=set(m['human_positive_ids']);errors=set(m['new_human_rejected_ids'])
 surviving=pool-removed-errors
 report={**{k:v for k,v in m.items() if not k.endswith('_ids')},'per_model_temporary':{model:len(s) for model,s in zip(m.get('active_models',MODELS),sets)},
 'temporary_union':len(removed),'pool_temporary_removed':len(pool&removed),'known_errors_identified':len(errors&removed),
 'known_errors_denominator':len(errors),'known_errors_explicitly_removed':len(pool&errors),
 'human_positive_falsely_removed':len(positives&removed),'human_positive_denominator':len(positives),
 'previous85_falsely_removed':len((positives-pool)&removed),'new69_falsely_removed':len(positives&pool&removed),
 'pool_surviving_after_temporal_and_owner_rejection':len(surviving),
 'proposed_pool_union_previous_human':len(surviving|(positives-pool)),
 'confirmed_only_gap_700':max(0,700-len(positives)),'confirmed_only_gap_1500':max(0,1500-len(positives)),
 'actual_adopted_model_pool':0,'owner_decision_pending':True,'phase1_accepted':False}
 write(out/'report.json',report);lines(out/'proposed-survivors-private.jsonl',[r for r in read_rows(out/'items.jsonl') if r['item_id'] in surviving])
 print(json.dumps(report,ensure_ascii=False))

if __name__=='__main__':
 os.umask(0o077);p=argparse.ArgumentParser();p.add_argument('action',choices=['prepare','screen','summary']);a=p.parse_args()
 if a.action=='prepare':prepare()
 elif a.action=='summary':summarize_screen()
 else:asyncio.run(run_screen())
