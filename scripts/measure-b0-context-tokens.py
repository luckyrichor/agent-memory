"""Measure B0's byte counter against the frozen target model's real tokenizer.

Standalone rendered-context tokens exclude the question and chat framing. This
is a measurement sidecar, never a replacement or optimization of the B0 counter.
"""
import argparse,asyncio,hashlib,json,os,time
from collections import defaultdict
from pathlib import Path
import httpx
from agent_memory.evals.metrics import ratio


def sha(value):return hashlib.sha256(value.encode()).hexdigest()


async def main():
 p=argparse.ArgumentParser();p.add_argument('--input',type=Path,required=True);p.add_argument('--output',type=Path,required=True);args=p.parse_args()
 if '.local' not in args.output.resolve().parts:raise ValueError('private output required')
 args.output.mkdir(parents=True,exist_ok=False,mode=0o700)
 source=args.input/'results-private.jsonl'
 snapshot=source.read_bytes()
 rows=[json.loads(s) for s in snapshot.decode().split('\n') if s.strip()]
 selected=[r for r in rows if r['system']=='system' and r['system_context'] is not None]
 semaphore=asyncio.Semaphore(4);records=[]
 async with httpx.AsyncClient(timeout=60,trust_env=False) as client:
  async def one(index,row):
   content=row['context'];body={'model':'doubao-seed-2-1-pro-260915','text':[content]};prefix=args.output/f'{index:05d}'
   prefix.with_suffix('.request-private.json').write_text(json.dumps(body,ensure_ascii=False));start=time.monotonic()
   async with semaphore:
    response=await client.post('https://ark.cn-beijing.volces.com/api/v3/tokenization',json=body,headers={'Authorization':'Bearer '+os.environ['ARK_API_KEY']})
   prefix.with_suffix('.response-private.json').write_text(response.text);data=response.json()
   count=data['data'][0]['total_tokens'] if response.is_success else None
   records.append({'row_id':row['row_id'],'conversation_id':row['conversation_id'],'dataset':row['dataset'],'mode':row['mode'],'repeat':row['repeat'],'rendered_sha256':sha(content),'byte_estimate':row['system_context']['used_tokens'],'declared_budget':row['system_context']['budget'],'actual_rendered_tokens':count,'http':response.status_code,'response_model':data.get('model'),'seconds':time.monotonic()-start,'usage':data.get('usage'),'new_http_call':True})
  await asyncio.gather(*(one(i,row) for i,row in enumerate(selected)))
 groups=defaultdict(list)
 for r in records:
  if r['actual_rendered_tokens'] is not None:groups[(r['dataset'],r['mode'])].append(r)
 result={}
 for key,values in groups.items():
  clusters=defaultdict(list)
  for r in values:clusters[r['conversation_id']].append(r)
  result['/'.join(key)]={'rows':len(values),'CX1_actual_context_tokens_per_declared_budget':ratio([(sum(r['actual_rendered_tokens'] for r in rs),sum(r['declared_budget'] for r in rs)) for rs in clusters.values()]).to_dict(),'CX2_excess_estimated_units_per_true_token':ratio([(sum(max(0,r['byte_estimate']-r['actual_rendered_tokens']) for r in rs),sum(r['actual_rendered_tokens'] for r in rs)) for rs in clusters.values()]).to_dict(),'estimated_byte_units':sum(r['byte_estimate'] for r in values),'true_context_tokens':sum(r['actual_rendered_tokens'] for r in values)}
 summary={'scope':'snapshot of prepared development rows; raw rendered-context tokenization only, excludes chat framing/question; does not change the B0 counter or budgets','model':'doubao-seed-2-1-pro-260915','dataset_snapshot_sha256':hashlib.sha256(snapshot).hexdigest(),'new_tokenizer_calls':len(records),'usage_not_reported_calls':sum(r['usage'] is None for r in records),'source_documentation':'https://docs.volcengine.com/docs/ark/tokenization-api?lang=en','results':result,'records':records}
 (args.output/'report-private.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
 for path in args.output.iterdir():path.chmod(0o600)
 print(json.dumps({'calls':len(records),'groups':list(result),'invalid':sum(r['http']!=200 for r in records)}))

if __name__=='__main__':asyncio.run(main())
