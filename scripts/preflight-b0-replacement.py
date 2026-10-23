"""Live replacement check on fictional events only; never edits frozen B0 prompts."""
import argparse,asyncio,hashlib,importlib.util,json
from pathlib import Path

async def main():
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args()
 if '.local' not in a.output.resolve().parts:raise ValueError('private output required')
 a.output.mkdir(parents=True,exist_ok=False,mode=0o700)
 spec=importlib.util.spec_from_file_location('b0_driver',Path('scripts/run-b0.py'));module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
 prompt=Path('docs/evals/prompts/b0-extraction-frozen-v1.txt').read_text()
 reports=[]
 for model,provider in [('doubao-seed-2-1-lite-260915','Ark'),('deepseek-v4.1-flash-1017','TokenHub')]:
  root=a.output/model;root.mkdir(mode=0o700);io=module.ModelIO(root)
  async def one(i):
   summary='A fictional build of comet-widget failed because the compiler target was missing; set the compiler target before rebuilding.' if i<5 else f'Fictional project nebula-{i} needs its test database initialized before running integration tests.'
   body={'model':model,'temperature':0,'thinking':{'type':'disabled'},'max_tokens':800,'response_format':{'type':'json_object'},'messages':[{'role':'system','content':prompt},{'role':'user','content':json.dumps({'event_type':'tool.result','summary':summary})}]}
   data=await io.request('replacement-preflight',body,provider=provider)
   try:
    message=data['choices'][0]['message'];value=json.loads(message['content'])
    valid=isinstance(value,dict) and set(value)=={'memories'} and isinstance(value['memories'],list) and len(value['memories'])<=3 and all(isinstance(x,dict) and set(x)=={'content'} and isinstance(x['content'],str) and 1<=len(x['content'].strip())<=2000 for x in value['memories'])
    disabled=not message.get('reasoning_content');version=data.get('model')
   except (KeyError,TypeError,ValueError):value=None;valid=False;disabled=False;version=None
   return {'valid':valid,'disabled_thinking_observed':disabled,'version':version,'value':value}
  first=await one(0)
  if not first['valid']:
   report={'model':model,'provider':provider,'passed':False,'calls':len(io.calls),'reason':'first actual call failed or invalid'}
  else:
   checks=[first,*await asyncio.gather(*(one(i) for i in range(1,105)))];valid=sum(x['valid'] for x in checks[5:]);consistent=len({json.dumps(x['value'],sort_keys=True) for x in checks[:5]})==1
   report={'model':model,'provider':provider,'passed':consistent and valid==100 and all(x['disabled_thinking_observed'] for x in checks),'consistent_5':consistent,'format_valid':valid,'format_n':len(checks[5:]),'calls':len(io.calls),'temperature':0,'thinking_requested':'disabled','fictional_only':True,'prompt_sha256':hashlib.sha256(prompt.encode()).hexdigest(),'response_versions':sorted({x['version'] for x in checks if x['version']})}
  module.write(root/'summary.json',report);reports.append(report);print(json.dumps(report),flush=True)
  for client in io.clients.values():await client.aclose()
  if report['passed']:break
 module.write(a.output/'summary.json',reports)

if __name__=='__main__':asyncio.run(main())
