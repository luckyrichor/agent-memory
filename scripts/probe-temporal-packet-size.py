"""Bounded real-wire format check only; never edit prompts, source, labels, or validation."""
import asyncio,importlib.util,json,os
from pathlib import Path
from agent_memory.evals.evidence_v3 import read_rows,sha
ROOT=Path('.local/phase1/round3/temporal-v1')
async def main():
 spec=importlib.util.spec_from_file_location('real_response_replay','scripts/temporal-annotation-client-v2.py');client=importlib.util.module_from_spec(spec);spec.loader.exec_module(client)
 pointer=json.loads((ROOT/'increment-current.json').read_text());root=Path(pointer['root']);state=json.loads((root/'state.json').read_text());batch=Path(state['active_batch_path'])
 items=read_rows(batch/'items.jsonl');model='hunyuan-turbos-vision-video-20250728';prompt=Path('docs/evals/prompts/labeling-guide-v3-temporal-v1.txt');out=ROOT/'packet-size-probe-v1';out.mkdir(exist_ok=True,mode=0o700)
 summary=[]
 for size in (1,2,4):
  directory=out/f'size-{size}'
  ok=await client.side(directory,model,items[:size],prompt,'annotation')
  checked=read_rows(directory/model/'checked.jsonl') if ok else []
  result={'size':size,'transport_complete':ok,'schema_valid':sum(r['schema_valid'] for r in checked),'citation_valid':sum(r['citation_valid'] for r in checked),'items':len(checked),'model':model,'prompt_sha256':sha(prompt),'quality_evidence':False,'candidate_modified':False,'validation_relaxed':False}
  summary.append(result);(out/'report.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(result),flush=True)
  if not ok:break
if __name__=='__main__':
 os.umask(0o077);asyncio.run(main())
