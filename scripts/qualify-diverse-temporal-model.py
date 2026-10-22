"""Distinct fictional v3 samples; reuse five unchanged repeated controls and one format case."""
import asyncio,json,os,time
from datetime import datetime,timezone
from pathlib import Path
import httpx
from agent_memory.evals.evidence_v3 import sha
from agent_memory.evals.model_policy import require_disabled_thinking
from agent_memory.evals.temporal import TemporalEvidenceBatch,check
BASE=Path('.local/phase1/round3/temporal-v1')
PRIOR=BASE/'annotation-qualification/hunyuan-role-latest'
OUT=BASE/'diverse-annotation-qualification/hunyuan-role-latest'
MODEL='hunyuan-role-latest'
PROMPT=Path('docs/evals/prompts/labeling-guide-v3-temporal-v1.txt')

async def main():
 OUT.mkdir(parents=True,exist_ok=True,mode=0o700)
 prior=json.loads((PRIOR/'progress.json').read_text())
 summary={'purpose':'repeated fictional schema stability only, not 100 distinct samples qualification',
  'saved_responses':len(prior),'issued_request_files':len(list(PRIOR.glob('*-request.json'))),
  'unique_request_sha256_count':len({sha(p) for p in PRIOR.glob('*-request.json')}),
  'reported_tokens':sum((r.get('usage') or {}).get('total_tokens',0) for r in prior),
  'interrupted_request_usage_unknown':len(list(PRIOR.glob('*-request.json')))-len(prior),
  'qualified':False,'cause':'generator varied a field absent from final wire payload; fixed in separate diverse run; old results preserved'}
 (PRIOR/'interrupted-summary.json').write_text(json.dumps(summary,indent=2)+'\n')
 votes=[r['decision'] for r in prior[:5]];assert len(votes)==5 and all(r.get('no_reasoning') for r in prior[:5])
 records=[];next_request=0
 async with httpx.AsyncClient(timeout=150,trust_env=False) as client:
  for n in range(100):
   saved=OUT/f'{n:03d}-result.json'
   if saved.exists():records.append(json.loads(saved.read_text()));continue
   if n==0:
    body=json.loads((PRIOR/'005-request.json').read_text());response=json.loads((PRIOR/'005-response-0-private.json').read_text())
    source=body['messages'][1]['content'];payload=json.loads(source);sources=payload['sources']['v'];entry=payload['items'][0]
    item={'item_id':entry['item_id'],'subject':entry['subject'],'candidate':entry['candidate'],'source':sources}
    cached=True
   else:
    temporary=n%2==1
    text=f'我今天借用虚构编号{n}的相机，今晚就归还。' if temporary else f'我从小一直喜欢收集虚构主题{n}的邮票，将来也会长期保持。'
    candidate=f'用户今天借用虚构编号{n}的相机' if temporary else f'用户长期喜欢收集虚构主题{n}的邮票'
    sources=[{'source_id':f'virtual-u-{n}','session_id':f'virtual-session-{n}','role':'user','text':text}]
    item={'item_id':f'virtual-{n}','subject':'当前用户','candidate':candidate,'source':sources}
    payload={'sources':{'v':sources},'items':[{'item_id':item['item_id'],'subject':item['subject'],'candidate':candidate,'source_ref':'v'}]}
    body={'model':MODEL,'temperature':0,'thinking':{'type':'disabled'},'max_tokens':1536,
     'messages':[{'role':'system','content':PROMPT.read_text()},{'role':'user','content':json.dumps(payload,ensure_ascii=False)}]};cached=False
   (OUT/f'{n:03d}-request.json').write_text(json.dumps(body,ensure_ascii=False)+'\n')
   record={'number':n,'model':MODEL,'cached':cached,'attempts':[]}
   try:
    if not cached:
     for attempt in range(3):
      await asyncio.sleep(max(0,next_request-time.monotonic()));next_request=time.monotonic()+3.1
      r=await client.post(os.environ['TENCENT_BASE_URL'].rstrip('/')+'/chat/completions',json=body,headers={'Authorization':'Bearer '+os.environ['TENCENT_API_KEY']})
      (OUT/f'{n:03d}-response-{attempt}-private.json').write_text(r.text);record['attempts'].append({'http':r.status_code})
      if r.status_code!=429:break
      code=(r.json().get('error') or {}).get('code')
      if code=='SetLimitExceeded':break
      next_request=time.monotonic()+60
     record['http']=r.status_code
     if not r.is_success:
      record['error_code']=(r.json().get('error') or {}).get('code');raise RuntimeError('HTTP failed')
     response=r.json()
    record['usage']=response.get('usage');require_disabled_thinking(response);record['no_reasoning']=True
    if response['choices'][0].get('finish_reason') not in ('stop',None):raise ValueError('truncated')
    labels=TemporalEvidenceBatch.model_validate_json(response['choices'][0]['message']['content']).labels
    if len(labels)!=1 or labels[0].item_id!=item['item_id']:raise ValueError('ID coverage')
    decision=check(labels[0],item)
    record.update(format_valid=True,citation_valid=decision['citation_valid'],label=decision['label'],temporal=labels[0].temporal)
   except Exception as exc:record.update(format_valid=False,error_type=type(exc).__name__)
   saved.write_text(json.dumps(record,indent=2)+'\n');records.append(record)
   (OUT/'progress.json').write_text(json.dumps(records,indent=2)+'\n')
   if not record.get('no_reasoning') or record.get('http') in (402,404):break
 result={'model':MODEL,'provider':'TokenHub','qualified_at':datetime.now(timezone.utc).isoformat(),
  'consistent_5':len(votes)==5 and all(v==votes[0] for v in votes),
  'format_n':len(records),'format_valid':sum(r.get('format_valid',False) for r in records),
  'distinct_inputs':len({sha(p) for p in OUT.glob('*-request.json')}),
  'observed_disabled_thinking':len(records)==100 and all(r.get('no_reasoning') for r in records),
  'citation_valid':sum(r.get('citation_valid',False) for r in records),
  'new_post_attempts':sum(len(r['attempts']) for r in records),
  'new_reported_tokens':sum((r.get('usage') or {}).get('total_tokens',0) for r in records if not r['cached']),
  'prompt_sha256':sha(PROMPT),'prior_repeated_control_summary_sha256':sha(PRIOR/'interrupted-summary.json'),
  'temperature_requested':0,'fictional_only':True,'schema':'full v3 evidence plus temporal'}
 result['passed']=result['consistent_5'] and result['format_n']==result['distinct_inputs']==100 and result['format_valid']>=99 and result['observed_disabled_thinking'] and result['citation_valid']>=99
 (OUT/'report.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result),flush=True)
if __name__=='__main__':
 os.umask(0o077);asyncio.run(main())
