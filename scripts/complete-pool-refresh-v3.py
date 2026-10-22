"""Explicit same-prompt recovery and audit finalization; never adjust provider limits."""
import argparse
import asyncio
import importlib.util
import json
import os
from pathlib import Path

from agent_memory.evals.approved_audit import prepare_joint_audit
from agent_memory.evals.evidence_v3 import read_rows, sha

ROOT=Path('.local/phase1/round3/pool-refresh-v3-v3')
DRIVER=Path('scripts/refresh-evidence-pool-v3-v3.py')


def driver():
 spec=importlib.util.spec_from_file_location('pool_v3_frozen_driver',DRIVER)
 module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
 module.verify()
 return module


def checked(model):
 rows=[r for p in sorted(ROOT.glob(f'pool-*/{model}/*-checked.jsonl')) for r in read_rows(p)]
 if len(rows)!=len({r['item_id'] for r in rows}):raise ValueError('duplicate resumed label')
 return {r['item_id']:r for r in rows}


async def recover():
 mod=driver();engine=mod.load_engine()
 items=read_rows(ROOT/'pool-items.jsonl')
 jobs=[]
 for model in mod.MODELS:
  done=checked(model);remaining=[r for r in items if r['item_id'] not in done]
  if not remaining:continue
  number=1
  while (ROOT/f'pool-recovery-{number}'/model).exists():number+=1
  stage=f'pool-recovery-{number}'
  path=ROOT/(stage+'-'+model+'-items.jsonl')
  mod.lines(path,remaining)
  (ROOT/(stage+'-'+model+'-manifest.json')).write_text(json.dumps({
   'reason':'explicit resume after owner restores same provider/model availability',
   'items_sha256':sha(path),'original_manifest_sha256':sha(ROOT/'manifest.json'),
   'script_sha256':sha(Path(__file__)),'prompt_sha256':sha(mod.PROMPT),
   'model':model,'items':len(remaining),'previous_labels_reused':len(done),
   'provider_limit_changes':False},indent=2)+'\n')
  jobs.append(engine.run_model(stage,model,remaining))
 if jobs and not all(await asyncio.gather(*jobs)):
  raise ValueError('provider still unavailable; stop and retain attempt')
 finalize()


def finalize():
 mod=driver();m=mod.verify()
 items=read_rows(ROOT/'pool-items.jsonl');pool={r['item_id'] for r in items}
 for model in mod.MODELS:
  rows=checked(model)
  if rows.keys()!=pool:raise ValueError('full paired coverage required; no audit allowed')
  output=ROOT/'final-combined'/model;output.mkdir(parents=True,exist_ok=True,mode=0o700)
  mod.lines(output/'checked.jsonl',[rows[k] for k in sorted(pool)])
  mod.lines(output/'labels.jsonl',[{f:rows[k][f] for f in ('item_id','label','reason')} for k in sorted(pool)])
 # This file contains real owner labels only, not the earlier blacklist placeholders.
 human=read_rows(mod.HUMAN)
 split=json.loads(mod.SPLIT.read_text())
 exposed=set(split['development'])|set(split['final'])|{r['item_id'] for r in human}
 assert exposed=={r['item_id'] for r in human}
 projected=[r for r in human if r['item_id'] in pool]
 mod.lines(ROOT/'real-owner-labels-pool-projection.jsonl',projected)
 audit=ROOT/'audit72-final'
 if audit.exists():raise ValueError('audit already frozen; never redraw')
 result=prepare_joint_audit(items=ROOT/'pool-items.jsonl',
    left=ROOT/'final-combined'/mod.MODELS[0]/'labels.jsonl',
    right=ROOT/'final-combined'/mod.MODELS[1]/'labels.jsonl',
    prior_human=ROOT/'real-owner-labels-pool-projection.jsonl',output=audit,
    seed=m['seed'],sample_size=m['sample'])
 mapping=json.loads((audit/'opaque-map-private.json').read_text())
 assert not set(mapping.values())&exposed
 assert result['owner_rejected_removed']==0  # original pool already removed owner rejects
 print(json.dumps({'audit':str(audit/'audit-blind.csv'),'sample':result['sample'],
                   'exposed_overlap':len(set(mapping.values())&exposed)}))


if __name__=='__main__':
 os.umask(0o077)
 p=argparse.ArgumentParser();p.add_argument('action',choices=['finalize','recover'])
 p.add_argument('--provider-restored',action='store_true');a=p.parse_args()
 if a.action=='recover':
  if not a.provider_restored:p.error('explicit --provider-restored required; never probe paused model automatically')
  asyncio.run(recover())
 else:finalize()
