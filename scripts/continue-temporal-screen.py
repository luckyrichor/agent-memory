"""Bounded whole-side quota replacement; never merge results from different models."""
import asyncio, importlib.util, json, os
from pathlib import Path

def module(path,name):
 spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

async def main():
 e=module('scripts/run-temporal-phase1.py','temporal_run')
 q=module('scripts/qualify-tokenhub-pool-model.py','temporal_qualification')
 e.prepare();out=e.ROOT/'screen';manifest=e.load(out/'manifest.json')
 rows=e.read_rows(out/'items.jsonl');prompt=Path('docs/evals/prompts/temporal-filter-v1.txt')
 active=list(e.MODELS);switches=[]
 for index,initial in enumerate(e.MODELS):
  if await e.side(out,initial,rows,prompt,'screen'):continue
  ledger=e.load(out/initial/'ledger.json');last=ledger[-1]
  if not last.get('quota_blocked'):raise RuntimeError('non-quota failure preserved; do not change semantic/format gate')
  candidates=('deepseek-v4-flash-202605','deepseek/deepseek-flash') if index==0 else ('hy3','hy-role','glm-5-2-260617')
  for candidate in candidates:
   if candidate=='glm-5-2-260617':
    proof=Path('.local/phase1/round3/ark/preflight-glm-5-2-260617/glm-5-2-260617-summary.json')
    summary=e.load(proof);qualified=summary['preflight_pass'] and summary['consistent_5'] and summary['format_valid']==100
   else:
    summary=await q.qualify(candidate);qualified=summary['passed']
   if not qualified:continue
   switches.append({'from':initial,'to':candidate,'cause':'HTTP 402 quota','whole_side_items':len(rows),
    'retired_partial_labels_used':False,'preflight':summary})
   e.write(out/'switches.json',switches)
   if await e.side(out,candidate,rows,prompt,'screen'):
    active[index]=candidate;break
   last=e.load(out/candidate/'ledger.json')[-1]
   if not last.get('quota_blocked'):raise RuntimeError('replacement non-quota failure; no gate relaxation')
  else:raise RuntimeError('bounded eligible replacement pool exhausted')
 manifest['active_models']=active;manifest['switches']=switches;e.write(out/'manifest.json',manifest)
 e.summarize_screen()

if __name__=='__main__':
 os.umask(0o077);asyncio.run(main())
