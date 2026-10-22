"""Five distinct real transport controls, no human labels or semantic tuning."""
import asyncio,importlib.util,json,os
from pathlib import Path
from agent_memory.evals.evidence_v3 import read_rows,sha
ROOT=Path('.local/phase1/round3/temporal-v1')
async def main():
 spec=importlib.util.spec_from_file_location('single_packet_client','scripts/temporal-annotation-client-v2.py');client=importlib.util.module_from_spec(spec);spec.loader.exec_module(client)
 pointer=json.loads((ROOT/'increment-current.json').read_text());root=Path(pointer['root']);state=json.loads((root/'state.json').read_text());items=read_rows(Path(state['active_batch_path'])/'items.jsonl')
 positions=[0,100,200,400,550];out=ROOT/'single-packet-real-controls-v1';out.mkdir(exist_ok=True,mode=0o700)
 excluded={r['item_id'] for r in items[:4]}|{items[n]['item_id'] for n in positions}
 (ROOT/'transport-probe-excluded-ids.json').write_text(json.dumps({'ids':sorted(excluded),'purpose':'conservative exclusion of real input used for transport debugging; no human labels consulted'},indent=2)+'\n')
 reports=[]
 for index in positions:
  directory=out/f'position-{index}'
  ok=await client.side(directory,'hunyuan-turbos-vision-video-20250728',[items[index]],Path('docs/evals/prompts/labeling-guide-v3-temporal-v1.txt'),'annotation')
  checked=read_rows(directory/'hunyuan-turbos-vision-video-20250728'/'checked.jsonl') if ok else []
  reports.append({'position':index,'complete':ok,'schema_valid':len(checked)==1 and checked[0]['schema_valid'],'citation_valid':len(checked)==1 and checked[0]['citation_valid']})
  result={'controls':reports,'all_format_and_quote_checks_passed':len(reports)==5 and all(r['schema_valid'] and r['citation_valid'] for r in reports),'human_quality_evidence':False,'prompt_unchanged':True,'validation_unchanged':True,'blind_pool_excluded_debug_items':len(excluded)}
  (out/'report.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(reports[-1]),flush=True)
  if not ok:break
if __name__=='__main__':
 os.umask(0o077);asyncio.run(main())
