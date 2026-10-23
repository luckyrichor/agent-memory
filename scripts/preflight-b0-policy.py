"""Apply the existing model qualification policy, preserving all live raw probes."""
import argparse,asyncio,hashlib,json
from pathlib import Path
import httpx
from agent_memory.evals import model_preflight as policy

async def main():
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args()
 if '.local' not in a.output.resolve().parts:raise ValueError('private output required')
 a.output.mkdir(parents=True,exist_ok=False,mode=0o700)
 model='deepseek-v4.1-flash-1017';prompt_path=Path('docs/evals/prompts/preflight-v1.txt');prompt=prompt_path.read_text();sem=asyncio.Semaphore(4)
 async with httpx.AsyncClient(timeout=60,trust_env=False) as client:
  async def one(i):
   async with sem:record,raw=await policy.probe(client,model,prompt,i,repeated=i<6)
   f=a.output/f'{i:03d}-private.json';f.write_text(json.dumps(raw,ensure_ascii=False));f.chmod(0o600)
   return record
  first=await one(0)
  records=[first,*await asyncio.gather(*(one(i) for i in range(1,106)))] if first.get('format_valid') else [first]
 repeated=records[1:6];formatted=records[6:]
 consistent=len(repeated)==5 and all(r.get('format_valid') for r in repeated) and len({r.get('label') for r in repeated})==1
 summary={'model':model,'provider':'TokenHub','standard_source':'src/agent_memory/evals/model_preflight.py','prompt_sha256':hashlib.sha256(prompt.encode()).hexdigest(),'temperature':0,'thinking_requested':'disabled','consistent_5_labels':consistent,'format_n':len(formatted),'format_valid':sum(bool(r.get('format_valid')) for r in formatted),'observed_disabled_thinking':all(r.get('observed_disabled_thinking') for r in records),'calls':len(records)}
 summary['passed']=len(formatted)==100 and summary['format_valid']>=99 and consistent and summary['observed_disabled_thinking'] and first.get('format_valid')
 f=a.output/'records-private.json';f.write_text(json.dumps(records));f.chmod(0o600)
 f=a.output/'summary.json';f.write_text(json.dumps(summary,indent=2));f.chmod(0o600)
 print(json.dumps(summary),flush=True)

if __name__=='__main__':asyncio.run(main())
