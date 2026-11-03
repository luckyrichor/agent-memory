"""Actual fictional role probe; embedding format checks do not impose judge-label equality."""
import argparse,asyncio,importlib.util,json
from pathlib import Path

async def main():
 p=argparse.ArgumentParser();p.add_argument('--profile',type=Path,required=True);p.add_argument('--role',required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
 a.output.mkdir(parents=True,exist_ok=False,mode=0o700);config=json.loads(a.profile.read_text())
 spec=importlib.util.spec_from_file_location('b0_driver',Path('scripts/run-b0.py'));module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
 io=module.ModelIO(a.output,config=config);role=a.role;valid=False;checks=[]
 try:
  if role=='embedding':
   first=await io.embedding('Fictional vector consistency control.')
   vectors=[first,*await asyncio.gather(*(io.embedding('Fictional vector consistency control.' if i<6 else f'Fictional vector format input {i}.') for i in range(1,106)),return_exceptions=True)]
   from agent_memory.evals.b0 import embedding_probe_observations
   checks=embedding_probe_observations(vectors);valid=checks['passed']
  elif role=='extraction':
   body={'model':config['extraction_model'],'temperature':0,'thinking':{'type':'disabled'},'response_format':{'type':'json_object'},'max_tokens':800,'messages':[{'role':'system','content':Path('docs/evals/prompts/b0-extraction-frozen-v1.txt').read_text()},{'role':'user','content':json.dumps({'event_type':'tool.result','summary':'Fictional build needs its generated fixtures initialized before running tests.'})}]}
   data=await io.request('extraction',body,provider=config.get('extraction_provider','Ark'));value=json.loads(data['choices'][0]['message']['content']);valid=set(value)=={'memories'} and isinstance(value['memories'],list) and len(value['memories'])<=3 and all(set(x)=={'content'} and isinstance(x['content'],str) and 1<=len(x['content'].strip())<=2000 for x in value['memories'])
  elif role=='answer':
   answer,_=await io.answer('What is the fictional color?','The fictional color is green.',config['answer_models'][0]);valid=isinstance(answer,str) and bool(answer.strip())
  else:
   model=config.get('judge_model','glm-5.2') if role=='judge' else config.get('cross_reference_model','hunyuan-role-latest');valid=await io.grade({'dataset':'fictional','question':'What is the fictional color?','reference':'green','answer':'green'},model,role=role) is not None
 except (RuntimeError,ValueError,KeyError,TypeError,AssertionError):valid=False
 finally:
  for client in io.clients.values():await client.aclose()
 if valid and role!='embedding':
  from agent_memory.evals.model_policy import require_disabled_thinking
  try:
   for record in io.calls:
    if record.get('http')==200:require_disabled_thinking(json.loads((a.output/f"calls/{record['call_id']:07d}-response-{record['attempt']}-private.json").read_text()))
  except (RuntimeError,ValueError,KeyError):valid=False
 summary={'role':role,'passed':valid,'checks':checks,'fictional_only':True,'http_attempts':len(io.calls),'format_standard':'same native runtime schema; embedding native1024 finite nonzero, actual success and100 format trials; exact repeat equality diagnostic only'};module.write(a.output/'summary.json',summary);print(json.dumps(summary),flush=True)

if __name__=='__main__':asyncio.run(main())
