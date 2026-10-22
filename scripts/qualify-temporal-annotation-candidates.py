"""Actual v3 temporal schema qualification on entirely fictional records; no owner answers."""
import asyncio,importlib.util,json,os,time
from datetime import datetime,timezone
from pathlib import Path
import httpx
from agent_memory.evals.evidence_v3 import sha
from agent_memory.evals.model_policy import require_disabled_thinking
from agent_memory.evals.temporal import TemporalEvidenceBatch,check
ROOT=Path('.local/phase1/round3/temporal-v1/annotation-qualification')
PROMPT=Path('docs/evals/prompts/labeling-guide-v3-temporal-v1.txt')

async def qualify(model):
 out=ROOT/model;out.mkdir(parents=True,exist_ok=True,mode=0o700)
 if (out/'report.json').exists():return json.loads((out/'report.json').read_text())
 records=[];votes=[];next_request=0
 async with httpx.AsyncClient(timeout=150,trust_env=False) as client:
  for n in range(105):
   repeated=n<5
   subject='virtual-user' if repeated else f'virtual-user-{n}'
   source=[{'source_id':'virtual-u','session_id':'virtual-session','role':'user','text':'我从小一直喜欢集邮，至今没有改变。'}]
   item={'item_id':'virtual-item','conversation_id':subject,'subject':'当前用户','source':source,'candidate':'用户长期喜欢集邮'}
   body={'model':model,'temperature':0,'thinking':{'type':'disabled'},'max_tokens':1536,
    'messages':[{'role':'system','content':PROMPT.read_text()},{'role':'user','content':json.dumps({'sources':{'v':source},'items':[{'item_id':item['item_id'],'subject':item['subject'],'candidate':item['candidate'],'source_ref':'v'}]},ensure_ascii=False)}]}
   record={'number':n,'repeated':repeated,'attempts':[],'model':model}
   saved=out/f'{n:03d}-result.json'
   if saved.exists():
    record=json.loads(saved.read_text());records.append(record)
    if repeated and record.get('decision'):votes.append(record['decision'])
    if not record.get('success'):break
    continue
   (out/f'{n:03d}-request.json').write_text(json.dumps(body,ensure_ascii=False)+'\n')
   try:
    for attempt in range(3):
     await asyncio.sleep(max(0,next_request-time.monotonic()));next_request=time.monotonic()+3.1
     r=await client.post(os.environ['TENCENT_BASE_URL'].rstrip('/')+'/chat/completions',json=body,headers={'Authorization':'Bearer '+os.environ['TENCENT_API_KEY']})
     (out/f'{n:03d}-response-{attempt}-private.json').write_text(r.text)
     record['attempts'].append({'http':r.status_code})
     if r.status_code!=429:break
     code=(r.json().get('error') or {}).get('code')
     if code=='SetLimitExceeded':break
     next_request=time.monotonic()+60
    record['http']=r.status_code
    if not r.is_success:
     record['error_code']=(r.json().get('error') or {}).get('code');raise RuntimeError('HTTP failed')
    d=r.json();record['usage']=d.get('usage');record['returned_model']=d.get('model');require_disabled_thinking(d)
    if d['choices'][0].get('finish_reason') not in ('stop',None):raise ValueError('truncated')
    labels=TemporalEvidenceBatch.model_validate_json(d['choices'][0]['message']['content']).labels
    if len(labels)!=1 or labels[0].item_id!=item['item_id']:raise ValueError('ID mismatch')
    decision=check(labels[0],item)
    record.update(success=True,format_valid=True,citation_valid=decision['citation_valid'],no_reasoning=True,decision={'label':labels[0].label,'temporal':labels[0].temporal})
    if repeated:votes.append(record['decision'])
   except Exception as exc:record.update(success=False,error_type=type(exc).__name__)
   saved.write_text(json.dumps(record,indent=2)+'\n');records.append(record)
   (out/'progress.json').write_text(json.dumps(records,indent=2)+'\n')
   if not record.get('success'):break
 result={'model':model,'provider':'TokenHub','schema':'v3 evidence plus temporal','fictional_only':True,'qualified_at':datetime.now(timezone.utc).isoformat(),
  'calls':sum(len(r['attempts']) for r in records),'format_n':sum(not r['repeated'] for r in records),
  'format_valid':sum(bool(r.get('format_valid')) for r in records if not r['repeated']),
  'consistent_5':len(votes)==5 and all(x==votes[0] for x in votes),
  'observed_disabled_thinking':len(records)==105 and all(r.get('no_reasoning') for r in records),
  'citation_valid':sum(bool(r.get('citation_valid')) for r in records),'reported_tokens':sum((r.get('usage') or {}).get('total_tokens',0) for r in records),
  'prompt_sha256':sha(PROMPT),'temperature_requested':0,'first_http':records[0].get('http'),'first_error':records[0].get('error_type')}
 result['passed']=result['consistent_5'] and result['format_n']==result['format_valid']==100 and result['observed_disabled_thinking'] and result['citation_valid']==105
 (out/'report.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result),flush=True);return result

async def main():
 for model in ('hunyuan-role-latest','hy-vision-2.0-instruct'):
  result=await qualify(model)
  if result['passed']:break
if __name__=='__main__':
 os.umask(0o077);asyncio.run(main())
