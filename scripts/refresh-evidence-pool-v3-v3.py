"""Owner-authorized 701-pool refresh; no new offline evaluation or incremental sampling."""
import argparse
import asyncio
import importlib.util
import json
import os
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from agent_memory.evals.approved_audit import prepare_joint_audit
from agent_memory.evals.evidence_v3 import read_rows, sha

ROOT=Path('.local/phase1/round3/pool-refresh-v3-v3')
ENGINE=Path('scripts/run-evidence-v3-replacement.py')
VALIDATOR=Path('src/agent_memory/evals/evidence_v3.py')
PROMPT=Path('docs/evals/prompts/labeling-guide-v3-evidence-v3.txt')
ITEMS=Path('.local/phase1/chinese-expansion-v2/dulemon/items.jsonl')
HUMAN=Path('.local/phase1/round3/verbatim-filter/run-final/human-confirmed-labels.jsonl')
SPLIT=Path('.local/phase1/round3/evidence-v3-replacement/split-private.json')
PAIR=Path('.local/phase1/chinese-guide-v2-full-fallback-resume1/dulemon')
OLD=[PAIR/('labels-'+model+'-run1/labels.jsonl') for model in ('deepseek-v4-pro','mimo-v2.6-flash')]
MODELS=('deepseek-v4-pro-ga-260813','hy4-preview')
SHARDS=2
SEED=20261025


def dump(path,data):
 path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
 path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')


def lines(path,rows):
 path.write_text(''.join(json.dumps(row,ensure_ascii=False)+'\n' for row in rows))


def load_engine():
 spec=importlib.util.spec_from_file_location('frozen_v3_replacement_engine',ENGINE)
 module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
 module.ROOT=ROOT;module.PROMPT=PROMPT
 assert module.MODELS==MODELS and module.BATCH_SIZE==8
 return module


def prepare():
 if (ROOT/'manifest.json').exists():raise ValueError('pool batch already frozen')
 ROOT.mkdir(parents=True,exist_ok=True,mode=0o700)
 items={r['item_id']:r for r in read_rows(ITEMS)}
 human={r['item_id']:r for r in read_rows(HUMAN)}
 old=[{r['item_id']:r for r in read_rows(p)} for p in OLD]
 assert old[0].keys()==old[1].keys()==items.keys()
 joint={k for k in items if all(x[k]['label']=='keep' for x in old)}
 rejected={k for k in joint if k in human and human[k]['label']!='keep'}
 pool=sorted(joint-rejected)
 assert len(joint)==711 and len(rejected)==10 and len(pool)==701
 split=json.loads(SPLIT.read_text())
 exposed=set(split['development'])|set(split['final'])|human.keys()
 assert exposed==human.keys()
 lines(ROOT/'pool-items.jsonl',[items[k] for k in pool])
 # Explicit exclusions may include records outside this pool. Label values here are NOT human results.
 lines(ROOT/'audit-exclusions-all.jsonl',[{'item_id':k,'label':'uncertain','reason':'prior-human-or-dev-or-final-exposure'} for k in sorted(exposed)])
 lines(ROOT/'audit-exclusions.jsonl',[{'item_id':k,'label':'uncertain','reason':'prior-human-or-dev-or-final-exposure'} for k in sorted(set(pool)&exposed)])
 batches=[pool[i:i+8] for i in range(0,len(pool),8)]
 for shard in range(SHARDS):
  wanted=[k for batch in batches[shard::SHARDS] for k in batch]
  lines(ROOT/f'pool-shard-{shard}-items.jsonl',[items[k] for k in wanted])
 dev_diagnosis={}
 for model in MODELS:
  folder=Path('.local/phase1/round3/evidence-v3-replacement/development')/model
  proofs=[r for p in sorted(folder.glob('*-proofs.jsonl')) for r in read_rows(p)]
  assert set(x['item_id'] for x in proofs)==set(split['development'])
  keeps=[r for r in proofs if r['label']=='keep']
  dev_diagnosis[model]={'development_records':len(proofs),'model_keep':len(keeps),
        'keep_empty_subject':sum(not r['evidence']['subject'] for r in keeps),
        'keep_empty_relation':sum(not r['evidence']['relation'] for r in keeps)}
 files=[ITEMS,HUMAN,SPLIT,*OLD,PROMPT,ENGINE,VALIDATOR,Path(__file__),ROOT/'pool-items.jsonl',
        ROOT/'audit-exclusions.jsonl',ROOT/'audit-exclusions-all.jsonl',*[ROOT/f'pool-shard-{s}-items.jsonl' for s in range(SHARDS)]]
 dump(ROOT/'manifest.json',{
  'version':'pool-refresh-v3-evidence-v3','authorization':'om_x100b62a2ee4f8ca0cffd78d2b53c6ef',
  'created_beijing':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
  'models':list(MODELS),'providers':{'deepseek-v4-pro-ga-260813':'Ark','hy4-preview':'TokenHub'},
  'old_joint_keep':len(joint),'human_rejected_in_joint':len(rejected),'pool':len(pool),
  'previously_exposed_in_pool':len(set(pool)&exposed),'unexposed_before_refresh':len(set(pool)-exposed),
  'exclusions':len(exposed),'seed':SEED,'sample':72,'maximum_errors':3,'shards_per_model':SHARDS,
  'batch_size':8,'development_diagnosis_only':dev_diagnosis,
  'historical_error_block':{'correct':8,'total':9,'meets_owner_gate':True,'source':'docs/reports/phase1-round3-evidence-v3-replacement-2026-10-22/report.json','not_a_new_prompt_validation':True},
  'retention_is_gate':False,'no_new_offline_evaluation':True,'no_final_response_read_for_prompt':True,
  'old_prompt_history':'docs/evals/prompts/labeling-guide-v3-evidence-v1.txt',
  'files':{str(p):sha(p) for p in files},'phase1_accepted':False,
 })
 print(json.dumps({'pool':len(pool),'unexposed':len(set(pool)-exposed),'development_diagnosis':dev_diagnosis}))


def verify():
 m=json.loads((ROOT/'manifest.json').read_text())
 for p,h in m['files'].items():
  if sha(Path(p))!=h:raise ValueError('frozen pool source changed: '+p)
 return m


async def run():
 verify();engine=load_engine()
 # Each model has two request streams; every item belongs to exactly one stream.
 jobs=[engine.run_model(f'pool-shard-{s}',model,read_rows(ROOT/f'pool-shard-{s}-items.jsonl'))
       for model in MODELS for s in range(SHARDS)]
 completed=await asyncio.gather(*jobs)
 if not all(completed):raise ValueError('pool annotation incomplete; retain progress, do not rotate')
 combine()


def combine():
 m=verify();items=read_rows(ROOT/'pool-items.jsonl');expected={r['item_id'] for r in items}
 for model in MODELS:
  folders=[ROOT/f'pool-shard-{s}'/model for s in range(SHARDS)]
  if not all((d/'COMPLETE').exists() for d in folders):raise ValueError('incomplete shard')
  rows=[r for d in folders for r in read_rows(d/'checked.jsonl')]
  if len(rows)!=len(expected) or {r['item_id'] for r in rows}!=expected:raise ValueError('pool coverage mismatch')
  result=ROOT/'combined'/model;result.mkdir(parents=True,exist_ok=True,mode=0o700)
  rows.sort(key=lambda r:r['item_id'])
  lines(result/'checked.jsonl',rows)
  lines(result/'labels.jsonl',[{k:r[k] for k in ('item_id','label','reason')} for r in rows])
  (result/'COMPLETE').write_text(sha(result/'checked.jsonl')+'\n')
 left,right=[ROOT/'combined'/model/'labels.jsonl' for model in MODELS]
 a,b=({r['item_id']:r for r in read_rows(p)} for p in (left,right))
 exposed={r['item_id'] for r in read_rows(ROOT/'audit-exclusions.jsonl')}
 joint={k for k in expected if a[k]['label']==b[k]['label']=='keep'}
 dump(ROOT/'yield-summary.json',{'pool':len(expected),'joint_keep':len(joint),'joint_retention':len(joint)/len(expected),
      'previously_exposed_survivors':len(joint&exposed),'unexposed_survivors':len(joint-exposed),
      'sample_required':m['sample'],'shortfall':max(0,m['sample']-len(joint-exposed)),
      'per_model':{model:dict(Counter(r['label'] for r in read_rows(ROOT/'combined'/model/'checked.jsonl'))) for model in MODELS},
      'gold_adopted':False,'incremental_started':False})
 if len(joint-exposed)>=m['sample'] and not (ROOT/'audit72').exists():
  prepare_joint_audit(items=ROOT/'pool-items.jsonl',left=left,right=right,
                      prior_human=ROOT/'audit-exclusions.jsonl',output=ROOT/'audit72',
                      seed=m['seed'],sample_size=m['sample'])
 print((ROOT/'yield-summary.json').read_text())


if __name__=='__main__':
 os.umask(0o077)
 p=argparse.ArgumentParser();p.add_argument('action',choices=['prepare','run','combine']);a=p.parse_args()
 if a.action=='prepare':prepare()
 elif a.action=='run':asyncio.run(run())
 else:combine()
