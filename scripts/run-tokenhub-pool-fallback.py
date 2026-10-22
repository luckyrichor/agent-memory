"""Whole-side TokenHub replacement, full unchanged HY4 replay and independent audit."""
import argparse,asyncio,importlib.util,json,os
from pathlib import Path

from agent_memory.evals.evidence_v3 import read_rows,sha
from agent_memory.evals.approved_audit import prepare_joint_audit

BASE=Path('.local/phase1/round3/tokenhub-pool-v4')
PRIOR=Path('.local/phase1/round3/pool-refresh-v3-v3')
PROMPT=Path('docs/evals/prompts/labeling-guide-v3-evidence-v3.txt')
ENGINE=Path('scripts/tokenhub-pool-annotation-engine.py')
MODEL='deepseek-v4.1-flash-1017'
SEED=20261025

def module(path,name):
 spec=importlib.util.spec_from_file_location(name,path)
 m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def root():return BASE/MODEL.replace('/','-')

def engine():
 m=module(ENGINE,'tokenhub_annotation_engine');m.ROOT=root();return m

def prepare():
 r=root();r.mkdir(parents=True,exist_ok=True,mode=0o700)
 if (r/'manifest.json').exists():raise ValueError('frozen replacement batch exists')
 prior_manifest=json.loads((PRIOR/'manifest.json').read_text())
 for p,h in prior_manifest['files'].items():assert sha(Path(p))==h
 qualification=Path('.local/phase1/round3/tokenhub-pool-qualification')/MODEL.replace('/','-')/'report.json'
 q=json.loads(qualification.read_text());assert q['passed']
 e=engine();items=read_rows(PRIOR/'pool-items.jsonl');ids={x['item_id'] for x in items}
 rows=[]
 for s in range(2):
  p=PRIOR/f'pool-shard-{s}'/'hy4-preview'/'checked.jsonl'
  assert sha(p)==(p.parent/'COMPLETE').read_text().strip()
  rows+=read_rows(p)
 assert len(rows)==len(ids) and {x['item_id'] for x in rows}==ids
 e.lines(r/'pool-items.jsonl',items);e.lines(r/'hy4-complete-checked.jsonl',rows)
 e.lines(r/'hy4-complete-labels.jsonl',[{k:x[k] for k in ('item_id','label','reason')} for x in rows])
 batches=[items[i:i+8] for i in range(0,len(items),8)]
 for s in range(2):e.lines(r/f'shard-{s}-items.jsonl',[x for batch in batches[s::2] for x in batch])
 files=[PRIOR/'manifest.json',PRIOR/'pool-items.jsonl',PROMPT,ENGINE,Path(__file__),qualification,
        Path('src/agent_memory/evals/evidence_v3.py'),r/'pool-items.jsonl',r/'hy4-complete-checked.jsonl',
        r/'hy4-complete-labels.jsonl',r/'shard-0-items.jsonl',r/'shard-1-items.jsonl']
 e.write(r/'manifest.json',{'version':'pool-tokenhub-v4','authorization':'om_x100b62a2b0bb448cdde412b912e6146',
    'changed_model':MODEL,'models':[MODEL,'hy4-preview'],'providers':['TokenHub','TokenHub'],
    'vendors':['DeepSeek','Tencent'],'changed_side_relabel_entire':len(items),
    'unchanged_hy4_full_replay':len(rows),'old_deepseek_partial_used':False,
    'hy4_replay_reason':'same full pool, same prompt, same model/provider, independent original calls',
    'response_format_mode':{MODEL:'omitted: service rejects optional JSON mode','hy4-preview':'json_object'},
    'validation_unchanged':True,'retention_is_gate':False,'new_offline_evaluation':False,
    'seed':SEED,'sample':72,'maximum_errors':3,'files':{str(p):sha(p) for p in files}})
 print(json.dumps({'new_model':MODEL,'new_full_side':len(items),'hy4_replay':len(rows)}))

def verify():
 m=json.loads((root()/'manifest.json').read_text())
 assert m['changed_model']==MODEL
 for p,h in m['files'].items():
  if sha(Path(p))!=h:raise ValueError('frozen substitution input changed: '+p)
 return m

async def schema():
 verify();e=engine()
 row={'item_id':'virtual','conversation_id':'virtual','subject':'当前用户',
      'candidate':'喜欢集邮','source':[{'source_id':'virtual-u1','role':'user','text':'我长期喜欢集邮。'}]}
 done=await e.run_model('schema-check',MODEL,[row])
 if not done:raise ValueError('v3 schema check incomplete')
 parsed=read_rows(root()/'schema-check'/MODEL/'checked.jsonl')
 if len(parsed)!=1 or parsed[0]['label']!='keep' or not parsed[0]['citation_valid']:
  raise ValueError('v3 schema check failed')
 (root()/'SCHEMA_COMPLETE').write_text(sha(PROMPT)+'\n')

async def run():
 verify()
 if not (root()/'SCHEMA_COMPLETE').exists():raise ValueError('schema check required')
 e=engine()
 result=await asyncio.gather(*(e.run_model(f'pool-shard-{s}',MODEL,read_rows(root()/f'shard-{s}-items.jsonl')) for s in range(2)))
 if not all(result):raise ValueError('replacement incomplete: preserve full-side progress, do not mix retired labels')
 finalize()

def finalize():
 m=verify();r=root();e=engine();items=read_rows(r/'pool-items.jsonl');ids={x['item_id'] for x in items}
 rows=[]
 for s in range(2):
  p=r/f'pool-shard-{s}'/MODEL/'checked.jsonl'
  if not (p.parent/'COMPLETE').exists():raise ValueError('replacement side incomplete')
  assert sha(p)==(p.parent/'COMPLETE').read_text().strip()
  rows+=read_rows(p)
 assert len(rows)==len(ids) and {x['item_id'] for x in rows}==ids
 e.lines(r/'replacement-complete-checked.jsonl',rows)
 e.lines(r/'replacement-complete-labels.jsonl',[{k:x[k] for k in ('item_id','label','reason')} for x in rows])
 human_path=Path('.local/phase1/round3/verbatim-filter/run-final/human-confirmed-labels.jsonl')
 split_path=Path('.local/phase1/round3/evidence-v3-replacement/split-private.json')
 human=read_rows(human_path);split=json.loads(split_path.read_text())
 exposed={x['item_id'] for x in human}|set(split['development'])|set(split['final'])
 assert exposed=={x['item_id'] for x in human}
 e.lines(r/'real-owner-pool-projection.jsonl',[x for x in human if x['item_id'] in ids])
 left={x['item_id']:x for x in rows};right={x['item_id']:x for x in read_rows(r/'hy4-complete-checked.jsonl')}
 joint={k for k in ids if left[k]['label']==right[k]['label']=='keep'}
 e.write(r/'yield-summary.json',{'pool':len(ids),'joint_keep':len(joint),'joint_retention':len(joint)/len(ids),
     'exposed_survivors':len(joint&exposed),'unexposed_survivors':len(joint-exposed),
     'known_exclusions':len(exposed),'sample':m['sample'],'phase1_accepted':False,'incremental_started':False})
 audit=r/'audit72'
 if audit.exists():return
 result=prepare_joint_audit(items=r/'pool-items.jsonl',left=r/'replacement-complete-labels.jsonl',
       right=r/'hy4-complete-labels.jsonl',prior_human=r/'real-owner-pool-projection.jsonl',
       output=audit,seed=m['seed'],sample_size=m['sample'])
 mapping=json.loads((audit/'opaque-map-private.json').read_text())
 assert not set(mapping.values())&exposed
 assert result['owner_rejected_removed']==0
 print(json.dumps({'joint_keep':len(joint),'unexposed':len(joint-exposed),'audit_sample':result['sample']}))

if __name__=='__main__':
 os.umask(0o077)
 p=argparse.ArgumentParser();p.add_argument('action',choices=['prepare','schema','run','finalize'])
 p.add_argument('--model',default=MODEL,choices=['deepseek-v4.1-flash-1017','deepseek-v4-flash-202605','deepseek/deepseek-flash'])
 a=p.parse_args();MODEL=a.model
 if a.action=='prepare':prepare()
 elif a.action=='finalize':finalize()
 else:asyncio.run(schema() if a.action=='schema' else run())
