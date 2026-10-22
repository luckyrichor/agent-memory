"""Seeded unused BOTH/train supplementation. No new points adopted before owner audit."""
import asyncio, hashlib, importlib.util, json, os, random, shutil, zipfile
from collections import Counter
from pathlib import Path
from agent_memory.evals.approved_audit import prepare_joint_audit
from agent_memory.evals.chinese_expansion import unsegment
from agent_memory.evals.evidence_v3 import sha, read_rows
from agent_memory.evals.pool_planning import source_record

def module(path,name):
 spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

e=module('scripts/run-temporal-phase1.py','temporal_engine')
ROOT=e.ROOT/'increment';SEED=20261027;AUDIT_SEED=20261028;BATCH_DIALOGUES=100
PROMPT=Path('docs/evals/prompts/labeling-guide-v3-temporal-v1.txt')
OVERRIDE_MODELS=None
REPLAY_ROOT=None

def initialize():
 ROOT.mkdir(parents=True,exist_ok=True,mode=0o700)
 path=ROOT/'manifest.json'
 if path.exists():
  m=e.load(path)
  for p,h in m['files'].items():assert sha(Path(p))==h,'frozen increment input changed'
  return m
 screen=e.load(e.ROOT/'screen/report.json')
 indices=e.load(Path('.local/phase1/round3/pool-refresh-v3-v3/reserve-indices-private.json'))
 random.Random(SEED).shuffle(indices)
 # Do not depend on acceptance of the old proposed filtered pool.
 target=max(72,700-screen['deduplicated_human_positive']+3)
 files=[PROMPT,Path('src/agent_memory/evals/temporal.py'),Path('src/agent_memory/evals/evidence_v3.py'),Path(__file__),Path('scripts/run-temporal-phase1.py'),Path('.local/phase1/data/DuLeMon.zip'),Path('.local/phase1/normalized-v3/dulemon-split.json'),e.ROOT/'human-all-original.jsonl']
 m={'seed':SEED,'audit_seed':AUDIT_SEED,'batch_dialogues':BATCH_DIALOGUES,'available_indices':indices,
  'models':OVERRIDE_MODELS or screen.get('active_models',screen['models']),'target_unreviewed_joint_keeps':target,
  'target_basis':'700 minus individually human-confirmed positives plus allowance of three final audit errors; no pending old-pool adoption assumed',
  'source':'DuLeMon/both/train.json','license':'parent Apache-2.0; archive has no separate license',
  'files':{str(p):sha(p) for p in files},'phase1_accepted':False,'new_points_adopted':0}
 e.write(path,m);return m

def prepare_batch(number,m):
 out=ROOT/f'batch-{number:03d}'
 if (out/'manifest.json').exists():return out
 selected=m['available_indices'][number*BATCH_DIALOGUES:(number+1)*BATCH_DIALOGUES]
 if not selected:raise ValueError('unused source reserve exhausted')
 with zipfile.ZipFile('.local/phase1/data/DuLeMon.zip') as z:
  raw=[json.loads(s) for s in z.read('DuLeMon/both/train.json').decode().splitlines() if s.strip()]
 split=e.load(Path('.local/phase1/normalized-v3/dulemon-split.json'))
 split_lookup={k:side for side,values in split.items() for k in values}
 corpus=[];items=[];source_hashes=[];split_counts=Counter()
 for index in selected:
  row=raw[index];h,n,error=source_record(row);assert error is None
  source_hashes.append(h);cid=f'dulemon-both-train:{index:04d}';source=[]
  split_counts[split_lookup[f'dulemon:DuLeMon/both/train.json:{index}']]+=1
  for t,turn in enumerate(row['conversation']):
   utterance=turn.partition('\t')[0];speaker,sep,text=utterance.partition(':');assert sep and speaker in ('Usr','Bot')
   source.append({'source_id':f'turn:{t}','session_id':cid,'role':'user' if speaker=='Usr' else 'assistant','text':unsegment(text)})
  corpus.append({'conversation_id':cid,'source':source})
  for field in ('user_said_persona','user_no_said_persona'):
   for i,persona in enumerate(row[field]):
    _,sep,fact=persona.partition(':');assert sep
    item_id=f"{cid}:candidate:{hashlib.sha256(f'{field}:{i}'.encode()).hexdigest()[:16]}"
    items.append({'item_id':item_id,'conversation_id':cid,'subject':'当前用户Usr','source':source,'candidate':'用户陈述：'+unsegment(fact)})
 assert len(source_hashes)==len(set(source_hashes))
 items.sort(key=lambda x:x['item_id']);e.lines(out/'items.jsonl',items);e.lines(out/'corpus.jsonl',corpus)
 e.write(out/'manifest.json',{'batch':number,'new_indices':selected,'conversations':len(selected),'candidates':len(items),
  'source_hashes':source_hashes,'split_counts':dict(split_counts),'source_split_inherited':True,'models':m['models'],
  'items_sha256':sha(out/'items.jsonl'),'prompt_sha256':sha(PROMPT),'incremental_approved':True,'gold_adopted':False})
 return out

async def batch(number,m):
 out=prepare_batch(number,m);rows=read_rows(out/'items.jsonl');manifest=e.load(out/'manifest.json')
 assert sha(out/'items.jsonl')==manifest['items_sha256'] and sha(PROMPT)==manifest['prompt_sha256']
 # Two independent shards per model, all exact items; merged only after complete side coverage.
 chunks=[rows[i:i+8] for i in range(0,len(rows),8)]
 async def model_side(model):
  if REPLAY_ROOT is not None:
   for shard in range(2):
    old=REPLAY_ROOT/out.name/f'shard-{shard}'/model.replace('/','-');dest=out/f'shard-{shard}'/model.replace('/','-')
    if (old/'COMPLETE').exists() and not dest.exists():
     dest.parent.mkdir(parents=True,exist_ok=True);shutil.copytree(old,dest)
  results=await asyncio.gather(*(e.side(out/f'shard-{s}',model,[r for c in chunks[s::2] for r in c],PROMPT,'annotation') for s in range(2)))
  if not all(results):return False
  merged=[r for s in range(2) for r in read_rows(out/f'shard-{s}'/model.replace('/','-')/'checked.jsonl')]
  assert len(merged)==len(rows) and {r['item_id'] for r in merged}=={r['item_id'] for r in rows}
  e.lines(out/model/'checked.jsonl',merged)
  e.lines(out/model/'labels.jsonl',[{k:r[k] for k in ('item_id','label','reason')} for r in merged]);return True
 results=await asyncio.gather(*(model_side(model) for model in m['models']))
 if not all(results):raise RuntimeError('increment batch incomplete; no adoption; preserve complete side and replace quota-blocked side as whole batch')
 left,right=({r['item_id']:r for r in read_rows(out/model/'checked.jsonl')} for model in m['models'])
 joint={k for k in left if left[k]['label']==right[k]['label']=='keep'}
 temporary={k for k in left if left[k]['temporal']=='临时' or right[k]['temporal']=='临时'}
 invalid={k for k in left if not left[k]['citation_valid'] or not right[k]['citation_valid']}
 report={'batch':number,'conversations':manifest['conversations'],'candidates':len(rows),'joint_keep':len(joint),
  'temporal_removed':len(temporary),'citation_invalid':len(invalid),
  'per_model':{model:{'keep':sum(r['label']=='keep' for r in side.values()),'temporary':sum(r['temporal']=='临时' for r in side.values()),'citation_invalid':sum(not r['citation_valid'] for r in side.values())} for model,side in zip(m['models'],(left,right))},
  'models':m['models'],'gold_adopted':False}
 e.write(out/'report.json',report);print(json.dumps(report),flush=True);return report

def export_audit(m,reports):
 items=[];left=[];right=[]
 for r in reports:
  out=ROOT/f"batch-{r['batch']:03d}";items+=read_rows(out/'items.jsonl')
  left+=read_rows(out/m['models'][0]/'labels.jsonl');right+=read_rows(out/m['models'][1]/'labels.jsonl')
 # Explicitly exclude every historic human/development/final item, and exact content duplicates.
 history=read_rows(e.ROOT/'human-all-original.jsonl');excluded={r['item_id'] for r in history}
 split=e.load(Path('.local/phase1/round3/evidence-v3-replacement/split-private.json'));excluded.update(split['development']);excluded.update(split['final'])
 olditems=read_rows(Path('.local/phase1/chinese-expansion-v2/dulemon/items.jsonl'))
 def content(r):return hashlib.sha256(json.dumps({k:r[k] for k in ('subject','candidate','source')},sort_keys=True,ensure_ascii=False).encode()).hexdigest()
 prior_contents={content(r) for r in olditems if r['item_id'] in excluded}
 eligible=[];seen=set();removed=0
 for r in items:
  h=content(r)
  if r['item_id'] in excluded or h in prior_contents or h in seen:removed+=1;continue
  seen.add(h);eligible.append(r)
 ids={r['item_id'] for r in eligible}
 e.lines(ROOT/'audit-items.jsonl',eligible);e.lines(ROOT/'audit-left.jsonl',[r for r in left if r['item_id'] in ids]);e.lines(ROOT/'audit-right.jsonl',[r for r in right if r['item_id'] in ids]);e.lines(ROOT/'audit-human-projection.jsonl',[])
 pack=ROOT/'audit72'
 if not pack.exists():prepare_joint_audit(items=ROOT/'audit-items.jsonl',left=ROOT/'audit-left.jsonl',right=ROOT/'audit-right.jsonl',prior_human=ROOT/'audit-human-projection.jsonl',output=pack,seed=AUDIT_SEED)
 mapping=e.load(pack/'opaque-map-private.json');assert not set(mapping.values())&excluded
 e.write(ROOT/'report.json',{'batches':reports,'conversations':sum(r['conversations'] for r in reports),'candidates':len(items),
  'joint_keep':sum(r['joint_keep'] for r in reports),'dedup_or_historical_removed':removed,
  'audit':e.load(pack/'manifest.json'),'new_points_adopted':0,'owner_audit_pending':True,'phase1_accepted':False,
  'remaining_unused_dialogues':len(m['available_indices'])-sum(r['conversations'] for r in reports)})

async def run_attempt():
 m=initialize();reports=[]
 for number in range((len(m['available_indices'])+BATCH_DIALOGUES-1)//BATCH_DIALOGUES):
  out=ROOT/f'batch-{number:03d}'
  report=e.load(out/'report.json') if (out/'report.json').exists() else await batch(number,m)
  reports.append(report)
  if sum(r['joint_keep'] for r in reports)>=m['target_unreviewed_joint_keeps']:break
 export_audit(m,reports)

async def main():
 global ROOT,OVERRIDE_MODELS,REPLAY_ROOT
 q=module('scripts/qualify-tokenhub-pool-model.py','increment_qualification')
 switches=[]
 for attempt in range(4):
  e.write(e.ROOT/'increment-current.json',{'root':str(ROOT),'switches':switches})
  try:
   await run_attempt();return
  except RuntimeError:
   blocked=[]
   for path in ROOT.glob('batch-*/shard-*/**/ledger.json'):
    records=e.load(path)
    if records and records[-1]['status']!='complete' and records[-1].get('quota_blocked'):
     blocked.append(records[-1]['requested_model'])
   if not blocked:raise
   m=e.load(ROOT/'manifest.json');models=list(m['models'])
   for old in sorted(set(blocked)):
    choices=('deepseek-v4-flash-202605','deepseek/deepseek-flash') if old.startswith('deepseek') else ('hy4-preview','hy3','hy-role','mimo-v2.6-flash','minimax-m3')
    for candidate in choices:
     if candidate in models or any(x['to']==candidate for x in switches):continue
     result=await q.qualify(candidate)
     if result['passed']:break
    else:
     e.write(ROOT/'BLOCKED.json',{'cause':'bounded prequalified replacement pool exhausted','models':models,'partial_adopted':False})
     raise RuntimeError('quota replacement candidates exhausted')
    models[models.index(old)]=candidate
    switches.append({'from':old,'to':candidate,'reason':'quota exhaustion','scope':'all selected incremental batches, entire changed side','old_partial_used':False})
   REPLAY_ROOT=ROOT;ROOT=e.ROOT/f'increment-attempt-{attempt+2}';OVERRIDE_MODELS=models
 raise RuntimeError('bounded whole-cohort replacement attempts exhausted')

if __name__=='__main__':
 os.umask(0o077);asyncio.run(main())
