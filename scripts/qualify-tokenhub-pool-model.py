"""Synthetic transport/control checks. No owner data, no balance queries."""
import asyncio,json,os
from pathlib import Path
import httpx
from agent_memory.evals.model_policy import require_disabled_thinking

ROOT=Path('.local/phase1/round3/tokenhub-pool-qualification')

async def qualify(model):
 out=ROOT/model.replace('/','-');out.mkdir(parents=True,exist_ok=True,mode=0o700)
 if (out/'report.json').exists():return json.loads((out/'report.json').read_text())
 records=[];replies=[];semaphore=asyncio.Semaphore(2)
 async with httpx.AsyncClient(timeout=90,trust_env=False) as client:
  async def one(n):
   repeated=n<5
   candidate='fact0' if repeated else f'fact{n}'
   reference=candidate if repeated or n%2==0 else 'different'
   body={'model':model,'temperature':0,'thinking':{'type':'disabled'},'max_tokens':256,
    'messages':[{'role':'system','content':'Return only JSON with exactly keys label and reason. If candidate equals reference output {"label":"keep","reason":"supported"}, otherwise {"label":"discard","reason":"missing"}. No markdown or explanation.'},
                {'role':'user','content':json.dumps({'candidate':candidate,'reference':reference})}]}
   record={'number':n,'model':model,'provider':'TokenHub','repeated':repeated}
   async with semaphore:
    try:
     r=await client.post(os.environ['TENCENT_BASE_URL'].rstrip('/')+'/chat/completions',
                        headers={'Authorization':'Bearer '+os.environ['TENCENT_API_KEY']},json=body)
     record['http']=r.status_code
     (out/f'{n:03d}-request.json').write_text(json.dumps(body)+'\n')
     (out/f'{n:03d}-response-private.json').write_text(r.text)
     if r.is_success:
      d=r.json();record['usage']=d.get('usage');require_disabled_thinking(d)
      parsed=json.loads(d['choices'][0]['message']['content'])
      record['format_valid']=isinstance(parsed,dict) and set(parsed)=={'label','reason'} and parsed['label'] in ('keep','discard') and parsed['reason'] in ('supported','missing')
      record['expected_correct']=parsed==({'label':'keep','reason':'supported'} if candidate==reference else {'label':'discard','reason':'missing'})
      if repeated:replies.append(parsed)
      record['no_reasoning']=True
     else:record['error_code']=(r.json().get('error') or {}).get('code')
    except Exception as exc:record['error_type']=type(exc).__name__
    records.append(record)
    (out/'progress.json').write_text(json.dumps(records,indent=2)+'\n')
    await asyncio.sleep(.25)
   return record
  # One current availability request first; fail fast before the rest.
  first=await one(0)
  if first.get('format_valid') and first.get('no_reasoning'):
   await asyncio.gather(*(one(n) for n in range(1,105)))
 result={'model':model,'provider':'TokenHub','calls':len(records),
   'consistent_5':len(replies)==5 and all(x==replies[0] for x in replies),
   'format_n':sum(not r['repeated'] for r in records),
   'format_valid':sum(bool(r.get('format_valid')) for r in records if not r['repeated']),
   'observed_disabled_thinking':bool(records) and all(r.get('no_reasoning') for r in records),
   'temperature_requested':0,'api_json_mode':False,
   'reported_tokens':sum((r.get('usage') or {}).get('total_tokens',0) for r in records)}
 result['passed']=result['consistent_5'] and result['format_n']==result['format_valid']==100 and result['observed_disabled_thinking']
 (out/'report.json').write_text(json.dumps(result,indent=2)+'\n')
 print(json.dumps(result),flush=True);return result

if __name__=='__main__':
 import sys
 os.umask(0o077);asyncio.run(qualify(sys.argv[1]))
