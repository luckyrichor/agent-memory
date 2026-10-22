"""Progress, actual cost and conditional planning; no additional model requests."""
import json
import math
from collections import Counter
from pathlib import Path

from agent_memory.evals.evidence_v3 import read_rows, sha
from agent_memory.evals.pool_planning import production_scenario

ROOT=Path('.local/phase1/round3/pool-refresh-v3-v3')
OLD=Path('.local/phase1/round3/pool-refresh-v3-v2')
MODELS=('deepseek-v4-pro-ga-260813','hy4-preview')
m=json.loads((ROOT/'manifest.json').read_text())
for p,h in m['files'].items():assert sha(Path(p))==h
pool={r['item_id']:r for r in read_rows(ROOT/'pool-items.jsonl')}
models={};observations={};ledgers=[];errors=[]
for model in MODELS:
 rows=[];ledger=[]
 for folder in sorted(ROOT.glob('pool-*')):
  if not folder.is_dir():continue
  d=folder/model
  for p in sorted(d.glob('*-checked.jsonl')):rows+=read_rows(p)
  if (d/'ledger.json').exists():ledger+=json.loads((d/'ledger.json').read_text())
 assert len({r['item_id'] for r in rows})==len(rows)
 assert {r['item_id'] for r in rows}<=pool.keys()
 observations[model]={r['item_id']:r for r in rows};ledgers+=ledger
 complete=len(rows)==len(pool)
 completed_entries=[x for x in ledger if x['status']=='complete']
 prompt_tokens=sum((x.get('usage') or {}).get('prompt_tokens',0) for x in completed_entries)
 completion_tokens=sum((x.get('usage') or {}).get('completion_tokens',0) for x in completed_entries)
 models[model]={'completed':len(rows),'total':len(pool),'complete':complete,
   'labels':dict(Counter(r['label'] for r in rows)),
   'keep_rate':sum(r['label']=='keep' for r in rows)/len(pool) if complete else None,
   'citation_invalid':sum(not r['citation_valid'] for r in rows),
   'citation_failure_codes':dict(Counter(c for r in rows for c in r['citation_failures'])),
   'usage_prompt_tokens':prompt_tokens,'usage_completion_tokens':completion_tokens,
   'reported_tokens_per_completed_item':(prompt_tokens+completion_tokens)/len(rows) if rows else None,
   'calls':len(ledger),'remaining_min_requests':math.ceil((len(pool)-len(rows))/m['batch_size'])}
 for x in ledger:
  if x['status']!='complete':
   p=ROOT/x['stage']/model/f"{x['offset']:04d}-response.json"
   d=json.loads(p.read_text()) if p.exists() else {}
   code=(d.get('error') or {}).get('code')
   errors.append({'model':model,'stage':x['stage'],'offset':x['offset'],
                 'http':x.get('http_status'),'code':code,'error_type':x.get('error_type'),
                 'meaning':'model paused by account-configured safety usage limit' if code=='SetLimitExceeded' else 'request/format failure',
                 'raw_response_sha256':sha(p) if p.exists() else None})
exposed={r['item_id'] for r in read_rows(ROOT/'audit-exclusions-all.jsonl')}
lower=upper=unseen_lower=unseen_upper=0
for k in pool:
 states=[observations[model].get(k) for model in MODELS]
 lower+=all(r is not None and r['label']=='keep' for r in states)
 upper+=all(r is None or r['label']=='keep' for r in states)
 if k not in exposed:
  unseen_lower+=all(r is not None and r['label']=='keep' for r in states)
  unseen_upper+=all(r is None or r['label']=='keep' for r in states)
complete=all(x['complete'] for x in models.values())
old_ledger=[r for p in sorted(OLD.glob('pool-shard-*/*/ledger.json')) for r in json.loads(p.read_text())]
reserve=json.loads((ROOT/'reserve-summary.json').read_text())
human=read_rows(Path('.local/phase1/round3/verbatim-filter/run-final/human-confirmed-labels.jsonl'))
confirmed=sum(x['label']=='keep' for x in human);gap=max(0,700-confirmed)
mean=reserve['candidates_per_available_dialogue']
# These are planning assumptions, not measured new-pair joint yields. No confidence claim.
scenarios=[]
for rate in (.05,.10,.20):
 s=production_scenario(gap=gap,candidates_per_dialogue=mean,candidate_survival=rate,precision_assumption=.95)
 s['reserve_dialogues_sufficient']=s['dialogues_estimated']<=reserve['available_field_valid_unique']
 scenarios.append(s)
# Historical pool-selection density used only to give an explicitly optimistic calibration.
# New models would review all new native candidates directly, not run the unavailable old pair.
selection_density=m['old_joint_keep']/len(read_rows(Path('.local/phase1/chinese-expansion-v2/dulemon/items.jsonl')))
optimistic_density=selection_density*upper/len(pool)
optimistic=production_scenario(gap=gap,candidates_per_dialogue=mean,candidate_survival=optimistic_density,precision_assumption=.95) if optimistic_density else None
if optimistic:
 optimistic.update(kind='optimistic partial-bound calibration, not observed joint yield',
   assumptions=['old joint density transports to new conversations',
     'all missing DeepSeek results among HY4 keeps also keep','95% future manual precision assumption, not confidence bound'],
   reserve_dialogues_sufficient=optimistic['dialogues_estimated']<=reserve['available_field_valid_unique'])
result={
 'status':'complete-awaiting-human' if complete else 'blocked-by-provider-usage-cap',
 'pool':len(pool),'models':models,'joint_complete':complete,
 'joint_keep':lower if complete else None,'joint_rate':lower/len(pool) if complete else None,
 'joint_keep_completion_bounds':[lower,upper],'unexposed_joint_completion_bounds':[unseen_lower,unseen_upper],'bounds_are_not_sampling_ci':True,
 'completed_both_items':len(observations[MODELS[0]].keys()&observations[MODELS[1]].keys()),
 'partial_items_sorted_not_random':True,'do_not_extrapolate_partial_joint_rate':True,
 'actual_calls_current_prompt':len(ledgers),'http_current':dict(Counter(str(r.get('http_status')) for r in ledgers)),
 'actual_calls_retired_format_attempt':len(old_ledger),'actual_calls_all':len(old_ledger)+len(ledgers),
 'reported_tokens_current':sum((r.get('usage') or {}).get('total_tokens',0) for r in ledgers),
 'reported_tokens_retired':sum((r.get('usage') or {}).get('total_tokens',0) for r in old_ledger),
 'missing_usage_calls_current':sum('usage' not in r for r in ledgers),
 'retired_attempt_not_mixed':True,'errors':errors,
 'historical_quality_gate':m['historical_error_block'],'retention_is_gate':False,
 'historical_retention_report_only':{'blind_correct':[19,63],'native_correct':[4,22]},
 'new_prompt_human_retention':'not newly evaluated; owner prohibited another offline evaluation',
 'human_confirmed_positive':confirmed,'gap_to_700':gap,'gap_to_1500':max(0,1500-confirmed),
 'reserve':reserve,'production_scenarios':scenarios,'optimistic_calibration':optimistic,
 'old_selection_density_for_calibration':selection_density,
 'new_pair_direct_review_cost':'2*ceil(native_candidates/8); original annotation pair not invoked; native candidate enumeration has zero LLM calls',
 'individual_manual_gold_note':'To reach 700 individually human-confirmed positives still requires 615 additional individual confirmations; model survivors do not count. Whole-pool acceptance is conditional on a passed independent audit and reported separately.',
 'audit_generated':(ROOT/'audit72-final/manifest.json').exists(),
 'audit_seed':m['seed'],'required_sample':m['sample'],'maximum_errors':m['maximum_errors'],
 'phase1_accepted':False,'incremental_started':False,'offline_evaluation_new_calls':0,
 'manifest_sha256':sha(ROOT/'manifest.json'),'reserve_summary_sha256':sha(ROOT/'reserve-summary.json'),
}
(ROOT/'progress-and-planning.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:result[k] for k in ['status','actual_calls_current_prompt','joint_keep_completion_bounds','human_confirmed_positive','gap_to_700','audit_generated']}))
