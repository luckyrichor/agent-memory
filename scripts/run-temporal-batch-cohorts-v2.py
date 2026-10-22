"""Freeze each 100-dialogue batch; replace an affected side in full, never splice a half batch."""
import asyncio,hashlib,importlib.util,json,os
from pathlib import Path
from agent_memory.evals.approved_audit import prepare_joint_audit
from agent_memory.evals.evidence_v3 import read_rows,sha

def module(path,name):
 spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

async def main():
 engine=module('scripts/run-temporal-increment.py','frozen_batch_engine')
 client=module('scripts/temporal-annotation-client.py','strict_item_client')
 engine.e.side=client.side
 e=engine.e;global_root=e.ROOT/'increment-batches-strict-output-v1';global_root.mkdir(parents=True,exist_ok=True,mode=0o700)
 manifest_path=global_root/'manifest.json'
 models=['deepseek-v4-flash-202605','hunyuan-role-latest']
 qualifications={
  models[0]:Path('.local/phase1/round3/tokenhub-pool-qualification-throttled-v1/deepseek-v4-flash-202605/report.json'),
  models[1]:e.ROOT/'diverse-annotation-qualification/hunyuan-role-latest/report.json',
  'deepseek/deepseek-flash':Path('.local/phase1/round3/tokenhub-pool-qualification/deepseek-deepseek-flash/report.json')}
 for model in models:assert e.load(qualifications[model])['passed']
 prior=e.load(e.ROOT/'increment/manifest.json')
 if manifest_path.exists():m=e.load(manifest_path)
 else:
  files=[Path(__file__),Path('scripts/run-temporal-increment.py'),Path('scripts/run-temporal-phase1.py'),Path('scripts/temporal-annotation-client.py'),Path('src/agent_memory/evals/temporal_output.py'),Path('scripts/qualify-full-temporal-model.py'),Path('src/agent_memory/evals/temporal_preflight.py'),engine.PROMPT,Path('src/agent_memory/evals/temporal.py'),Path('src/agent_memory/evals/evidence_v3.py')]
  m={**prior,'models':models,'files':{str(p):sha(p) for p in files},
   'batch_switch_scope':'current fixed 100-dialogue batch, entire affected side; completed prior batches remain independently frozen with provenance; no partial model splice',
   'output_policy':'strict schemas and exact quote checks unchanged; individually rejected records become program-uncertain, never keep/discard; provider responses unmodified; genuine raw-response cache replay only','previous_failed_cohorts_retired':True,'historical_whole_cohort_restart_superseded_before_first_completed_increment_batch':True}
  e.write(manifest_path,m)
 for path,h in m['files'].items():assert sha(Path(path))==h,'frozen batch controller inputs changed'
 completed=e.load(global_root/'batch-registry.json') if (global_root/'batch-registry.json').exists() else []
 switches=e.load(global_root/'switches.json') if (global_root/'switches.json').exists() else []
 if completed:models=completed[-1]['models']
 blocked=None;attempt_root=None
 full_qualifier=module('scripts/qualify-full-temporal-model.py','full_schema_qualification')
 async def candidate_ok(candidate):
  if candidate in qualifications:return bool(e.load(qualifications[candidate])['passed'])
  result=await full_qualifier.qualify(candidate)
  return result['passed']
 def state(active=None):
  e.write(e.ROOT/'increment-current.json',{'root':str(global_root),'format':'batch-registry-v1','switches':switches})
  e.write(global_root/'state.json',{'active_batch_path':str(active) if active else None,'completed_batches':len(completed),'models':models,'blocked':blocked})
 async def summarize_and_maybe_finish(final=False):
  items=[];left=[];right=[];provenance=[]
  for entry in completed:
   path=Path(entry['path']);rows=read_rows(path/'items.jsonl');items+=rows
   a,b=entry['models'];left+=read_rows(path/a/'labels.jsonl');right+=read_rows(path/b/'labels.jsonl')
   provenance += [{'item_id':r['item_id'],'batch':entry['batch'],'models':entry['models'],'prompt_sha256':sha(engine.PROMPT)} for r in rows]
  old=read_rows(e.ROOT/'human-all-original.jsonl');excluded={r['item_id'] for r in old}
  split=e.load(Path('.local/phase1/round3/evidence-v3-replacement/split-private.json'));excluded.update(split['development']);excluded.update(split['final'])
  olditems=read_rows(Path('.local/phase1/chinese-expansion-v2/dulemon/items.jsonl'))
  def content(r):return hashlib.sha256(json.dumps({k:r[k] for k in ('subject','candidate','source')},sort_keys=True,ensure_ascii=False).encode()).hexdigest()
  seen={content(r) for r in olditems if r['item_id'] in excluded};eligible=[];removed=0
  for row in items:
   h=content(row)
   if row['item_id'] in excluded or h in seen:removed+=1;continue
   seen.add(h);eligible.append(row)
  ids={r['item_id'] for r in eligible};a={r['item_id']:r for r in left};b={r['item_id']:r for r in right}
  joint={k for k in ids if a[k]['label']==b[k]['label']=='keep'}
  current={'batches':completed,'conversations':sum(r['conversations'] for r in completed),'candidates':len(items),
   'joint_keep':len(joint),'raw_joint_keep':sum(r['joint_keep'] for r in completed),'dedup_or_historical_removed':removed,
   'target_unreviewed_joint_keeps':m['target_unreviewed_joint_keeps'],'target_reached':len(joint)>=m['target_unreviewed_joint_keeps'],
   'new_points_adopted':0,'owner_audit_pending':False,'phase1_accepted':False,'blocked':blocked,'complete':final,
   'remaining_unused_dialogues':len(m['available_indices'])-sum(r['conversations'] for r in completed),
   'unfinished_current_batch_excluded_from_gold':bool(blocked)}
  if final and len(joint)>=72:
   e.lines(global_root/'audit-items.jsonl',eligible);e.lines(global_root/'audit-left.jsonl',[r for r in left if r['item_id'] in ids]);e.lines(global_root/'audit-right.jsonl',[r for r in right if r['item_id'] in ids]);e.lines(global_root/'audit-human-projection.jsonl',[])
   e.lines(global_root/'item-model-provenance-private.jsonl',provenance)
   pack=global_root/'audit72'
   if not pack.exists():prepare_joint_audit(items=global_root/'audit-items.jsonl',left=global_root/'audit-left.jsonl',right=global_root/'audit-right.jsonl',prior_human=global_root/'audit-human-projection.jsonl',output=pack,seed=m['audit_seed'])
   aliases=e.load(pack/'opaque-map-private.json');assert not set(aliases.values())&excluded
   current.update(audit=e.load(pack/'manifest.json'),owner_audit_pending=True)
  elif final:current['audit_unavailable_reason']='fewer than72 fully completed independent joint keeps'
  e.write(global_root/'report.json',current)
  return current
 state()
 for number in range(len(completed),(len(m['available_indices'])+m['batch_dialogues']-1)//m['batch_dialogues']):
  replay=e.ROOT/'increment-attempt-2' if number==0 else None
  tried=set()
  for attempt in range(5):
   attempt_root=global_root/f'cohort-{number:03d}-attempt-{attempt:02d}'
   engine.ROOT=attempt_root;engine.REPLAY_ROOT=None  # replay raw responses through the unchanged strict validator, not old normalized labels
   local={**m,'models':models};path=engine.prepare_batch(number,local);state(path)
   if replay and (replay/path.name/'items.jsonl').exists():assert sha(path/'items.jsonl')==sha(replay/path.name/'items.jsonl')
   try:
    result=await engine.batch(number,local)
    aa,bb=({r['item_id']:r for r in read_rows(path/model/'checked.jsonl')} for model in models)
    result['invalid_evidence_total']=result['citation_invalid']
    result['schema_invalid']=sum(not aa[k]['schema_valid'] or not bb[k]['schema_valid'] for k in aa)
    result['citation_invalid']=sum((aa[k]['schema_valid'] and not aa[k]['citation_valid']) or (bb[k]['schema_valid'] and not bb[k]['citation_valid']) for k in aa)
    result['program_uncertain']=sum(aa[k]['program_uncertain'] or bb[k]['program_uncertain'] for k in aa)
    e.write(path/'report.json',result)
    record={**result,'path':str(path),'models':list(models),'whole_batch_frozen':True}
    completed.append(record);e.write(global_root/'batch-registry.json',completed)
    print(json.dumps({'batch_frozen':number,'conversations':record['conversations'],'candidates':record['candidates'],'joint_keep':record['joint_keep'],'temporal_marked_excluded':record['temporal_removed'],'citation_invalid':record['citation_invalid'],'models':models}),flush=True)
    break
   except RuntimeError:
    failed=[]
    for model in models:
     for ledger in path.glob('shard-*/'+model.replace('/','-')+'/ledger.json'):
      rows=e.load(ledger)
      if rows and rows[-1]['status']!='complete':failed.append(rows[-1])
    if not failed:raise
    changed=False
    for old_model in sorted({r['requested_model'] for r in failed}):
     last=next(r for r in failed if r['requested_model']==old_model)
     choices=['deepseek/deepseek-flash'] if old_model.startswith('deepseek') else ['hy-vision-2.0-instruct']
     for candidate in choices:
      if candidate in models or candidate in tried:continue
      tried.add(candidate)
      if await candidate_ok(candidate):
       new=list(models);new[new.index(old_model)]=candidate
       switches.append({'batch':number,'from':old_model,'to':candidate,'reason':'quota' if last.get('quota_blocked') else 'persistent transport/schema failure after bounded retries','scope':'entire affected side of current fixed batch','retired_partial_used':False})
       models=new;changed=True;break
     else:
      blocked={'batch':number,'model':old_model,'http':last.get('http'),'error_code':last.get('error_code'),'error_type':last.get('error_type'),'cause':'no further qualified independent available candidate in bounded pool'}
      e.write(global_root/'switches.json',switches);state(path)
      await summarize_and_maybe_finish(final=True);return
    if not changed:raise RuntimeError('no eligible replacement')
    e.write(global_root/'switches.json',switches);replay=attempt_root
  else:
   blocked={'cause':'bounded replacement attempts exhausted','batch':number};break
  current=await summarize_and_maybe_finish()
  if current['target_reached']:break
 state();await summarize_and_maybe_finish(final=True)

if __name__=='__main__':
 os.umask(0o077);asyncio.run(main())
