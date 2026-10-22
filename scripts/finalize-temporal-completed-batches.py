"""Close a blocked attempt using complete batches only; no failed partial side becomes gold."""
import hashlib,json
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
from agent_memory.evals.approved_audit import prepare_joint_audit
from agent_memory.evals.evidence_v3 import read_rows,sha
ROOT=Path('.local/phase1/round3/temporal-v1')

def load(p):return json.loads(p.read_text())
def write(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n')
def lines(p,rows):p.write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows))
def content(row):return hashlib.sha256(json.dumps({k:row[k] for k in ('subject','candidate','source')},sort_keys=True,ensure_ascii=False).encode()).hexdigest()

def main():
 root=Path(load(ROOT/'increment-current.json')['root']);state=load(root/'state.json');m=load(root/'manifest.json')
 for p,h in m['files'].items():assert sha(Path(p))==h
 registry=load(root/'batch-registry.json');active=Path(state['active_batch_path'])
 model='hunyuan-turbos-vision-video-20250728';observations=[]
 for p in active.glob('shard-*/'+model+'/ledger.json'):
  entries=load(p)
  for entry in entries:
   checked=p.parent/f"{entry['offset']:04d}-checked.jsonl"
   if entry['status']=='complete' and checked.exists():
    rows=read_rows(checked)
    observations.append({'items':len(rows),'all_response_invalid':all(r['reason']=='response-invalid' for r in rows),'ledger':str(p),'offset':entry['offset']})
 assert len(observations)>=3 and all(r['all_response_invalid'] for r in observations),'persistent whole-response failure not established'
 blocker={'at':datetime.now(timezone.utc).isoformat(),'batch':len(registry),'model':model,
  'cause':'persistent real multi-candidate root-schema failure despite successful single-item fictional preflight',
  'completed_responses':len(observations),'rejected_items':sum(r['items'] for r in observations),'valid_items':0,
  'partial_batch_excluded':True,'other_qualified_available_batched_candidate_in_current_pool':False,
  'scope':'bounded tested pool, not a claim that every catalog model is unavailable',
  'no_response_shape_repair_or_validation_relaxation':True,'observations':observations}
 write(ROOT/'actual-format-blocker.json',blocker)
 items=[];left=[];right=[];provenance=[]
 for entry in registry:
  p=Path(entry['path']);rows=read_rows(p/'items.jsonl');items+=rows
  a,b=entry['models'];left+=read_rows(p/a/'labels.jsonl');right+=read_rows(p/b/'labels.jsonl')
  provenance += [{'item_id':r['item_id'],'batch':entry['batch'],'models':entry['models'],'prompt_sha256':sha(Path('docs/evals/prompts/labeling-guide-v3-temporal-v1.txt'))} for r in rows]
 excluded={r['item_id'] for r in read_rows(ROOT/'human-all-original.jsonl')}
 split=load(Path('.local/phase1/round3/evidence-v3-replacement/split-private.json'));excluded.update(split['development']);excluded.update(split['final'])
 old=read_rows(Path('.local/phase1/chinese-expansion-v2/dulemon/items.jsonl'));seen={content(r) for r in old if r['item_id'] in excluded}
 eligible=[];removed=0
 for row in items:
  h=content(row)
  if row['item_id'] in excluded or h in seen:removed+=1;continue
  seen.add(h);eligible.append(row)
 ids={r['item_id'] for r in eligible};a={r['item_id']:r for r in left};b={r['item_id']:r for r in right}
 joint={key for key in ids if a[key]['label']==b[key]['label']=='keep'}
 lines(root/'audit-items.jsonl',eligible);lines(root/'audit-left.jsonl',[r for r in left if r['item_id'] in ids]);lines(root/'audit-right.jsonl',[r for r in right if r['item_id'] in ids]);lines(root/'audit-human-projection.jsonl',[])
 lines(root/'item-model-provenance-private.jsonl',provenance)
 pack=root/'audit72'
 if not pack.exists():prepare_joint_audit(items=root/'audit-items.jsonl',left=root/'audit-left.jsonl',right=root/'audit-right.jsonl',prior_human=root/'audit-human-projection.jsonl',output=pack,seed=m['audit_seed'])
 assert not set(load(pack/'opaque-map-private.json').values())&excluded
 report={'batches':registry,'conversations':sum(r['conversations'] for r in registry),'candidates':len(items),'joint_keep':len(joint),
  'raw_joint_keep':sum(r['joint_keep'] for r in registry),'dedup_or_historical_removed':removed,'target_unreviewed_joint_keeps':m['target_unreviewed_joint_keeps'],
  'target_reached':len(joint)>=m['target_unreviewed_joint_keeps'],'new_points_adopted':0,'owner_audit_pending':False,
  'owner_audit_issued':False,'audit_prepared_private_only':True,'audit_export_deferred_until_supplement_complete':True,
  'phase1_accepted':False,'blocked':blocker,'complete':True,'collection_attempt_closed':True,'supplement_complete':False,
  'unfinished_current_batch_excluded_from_gold':True,'audit':load(pack/'manifest.json'),
  'private_preview_not_human_evidence':True,'unresolved_target_joint_keeps':max(0,m['target_unreviewed_joint_keeps']-len(joint)),
  'human_confirmed_positive':len(read_rows(ROOT/'human-positive-labels.jsonl'))}
 report['conditional_reliable_if_partial_pool_later_audited_with_maximum_errors']=report['human_confirmed_positive']+len(joint)-report['audit']['maximum_errors']
 write(root/'report.json',report);write(root/'state.json',{**state,'blocked':blocker,'active_process_running':False})
 write(root/'finalization-manifest.json',{'script':str(Path(__file__)),'script_sha256':sha(Path(__file__)),'frozen_manifest_sha256':sha(root/'manifest.json'),'batch_registry_sha256':sha(root/'batch-registry.json'),'blocker_sha256':sha(ROOT/'actual-format-blocker.json'),'at':datetime.now(timezone.utc).isoformat()})
 print(json.dumps({k:report[k] for k in ('conversations','candidates','joint_keep','target_reached','unresolved_target_joint_keeps','new_points_adopted','owner_audit_issued','supplement_complete','phase1_accepted')}))
if __name__=='__main__':main()
