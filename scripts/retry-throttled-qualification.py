"""Resume only ordinary-429 virtual preflight requests, preserving original failed reports."""
import asyncio,json,os,time
from datetime import datetime,timezone
from pathlib import Path
import httpx
from agent_memory.evals.evidence_v3 import sha
from agent_memory.evals.model_policy import require_disabled_thinking
ROOT=Path('.local/phase1/round3/tokenhub-pool-qualification-throttled-v1')
PRIOR=Path('.local/phase1/round3/tokenhub-pool-qualification')

async def qualify(model):
 old=PRIOR/model.replace('/','-');out=ROOT/model.replace('/','-');out.mkdir(parents=True,exist_ok=True,mode=0o700)
 if (out/'report.json').exists():return json.loads((out/'report.json').read_text())
 old_progress=json.loads((old/'progress.json').read_text());by_n={r['number']:r for r in old_progress}
 assert len(by_n)==105
 records=[];replies=[];next_time=0
 async with httpx.AsyncClient(timeout=90,trust_env=False) as client:
  for n in range(105):
   body=json.loads((old/f'{n:03d}-request.json').read_text());record={'number':n,'model':model,'provider':'TokenHub','attempts':[],'repeated':n<5}
   previous=by_n[n]
   if previous.get('http')==200:
    raw=(old/f'{n:03d}-response-private.json').read_text();record['cached']=True
   elif previous.get('http')==429 and previous.get('error_code')!='SetLimitExceeded':
    record['cached']=False
    for attempt in range(3):
     saved=out/f'{n:03d}-response-{attempt}-private.json'
     if saved.exists():raw=saved.read_text();http=json.loads((out/f'{n:03d}-http-{attempt}.json').read_text())['http']
     else:
      await asyncio.sleep(max(0,next_time-time.monotonic()));next_time=time.monotonic()+3.1
      r=await client.post(os.environ['TENCENT_BASE_URL'].rstrip('/')+'/chat/completions',json=body,headers={'Authorization':'Bearer '+os.environ['TENCENT_API_KEY']})
      raw=r.text;http=r.status_code;saved.write_text(raw);(out/f'{n:03d}-http-{attempt}.json').write_text(json.dumps({'http':http})+'\n')
     record['attempts'].append({'http':http})
     if http==200:break
     error=(json.loads(raw).get('error') or {}).get('code')
     record['error_code']=error
     if http==402 or error=='SetLimitExceeded':break
     if http!=429:break
     await asyncio.sleep(30)
    record['http']=http
    if http!=200:
     records.append(record);break
   else:
    record['http']=previous.get('http');record['blocked']=True;records.append(record);break
   try:
    d=json.loads(raw);record['usage']=d.get('usage');require_disabled_thinking(d)
    parsed=json.loads(d['choices'][0]['message']['content'])
    record['format_valid']=isinstance(parsed,dict) and set(parsed)=={'label','reason'} and parsed['label'] in ('keep','discard') and parsed['reason'] in ('supported','missing')
    record['no_reasoning']=True
    if n<5:replies.append(parsed)
   except Exception as exc:record['error_type']=type(exc).__name__
   records.append(record);(out/'progress.json').write_text(json.dumps(records,indent=2)+'\n')
 result={'model':model,'provider':'TokenHub','qualified_at':datetime.now(timezone.utc).isoformat(),
  'consistent_5':len(replies)==5 and all(r==replies[0] for r in replies),
  'format_n':sum(not r['repeated'] for r in records),'format_valid':sum(bool(r.get('format_valid')) for r in records if not r['repeated']),
  'observed_disabled_thinking':len(records)==105 and all(r.get('no_reasoning') for r in records),
  'new_post_attempts':sum(len(r['attempts']) for r in records),'cached_successes':sum(bool(r.get('cached')) for r in records),
  'new_reported_tokens':sum((r.get('usage') or {}).get('total_tokens',0) for r in records if not r.get('cached')),
  'original_failed_report_sha256':sha(old/'report.json'),'temperature_requested':0,'same_virtual_requests':True,
  'retry_rule':'only ordinary429, at most two retries/request; 3.1s minimum pacing plus30s after429; no quota/limit modification'}
 result['passed']=result['consistent_5'] and result['format_n']==result['format_valid']==100 and result['observed_disabled_thinking']
 (out/'report.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result),flush=True);return result

async def main():
 for model in ('deepseek-v4-flash-202605','hy-role'):await qualify(model)
if __name__=='__main__':
 os.umask(0o077);asyncio.run(main())
