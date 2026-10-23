"""Estimate next sampled workload from measured replacement pilot, without model calls."""
import collections,json,math,random
from pathlib import Path

root=Path('.local/phase2/b0/api-pilot-lite-v1');usage=[json.loads(s) for s in (root/'usage.jsonl').open()]
roles={}
for role in sorted({r['role'] for r in usage}):
 r=[x for x in usage if x['role']==role and not x.get('cache_hit')];known=[x for x in r if x.get('usage')]
 roles[role]={'new_http_attempts':len(r),'usage_reported':len(known),'usage_unknown':len(r)-len(known),'total_reported_tokens':sum(x['usage'].get('total_tokens',0) for x in known),'mean_reported_tokens':sum(x['usage'].get('total_tokens',0) for x in known)/len(known) if known else None}
config=json.loads(Path('docs/baselines/b0/config-sample-v4.json').read_text());config.pop('conversations_per_question_type',None)
config['conversations_per_dataset']={'longmemeval_oracle':5,'longmemeval_s':2,'locomo':1,'perltqa_zh':3,'chinese_queries_v2':10,'dulemon_gold':8,'ecd_negative':8}
config['purpose']='budgeted dev sample after actual lite pilot; complete selected histories, 3 repeats, no test use; report unseen types and sampling limitations'
config['embedding_cache_roots'].append(str(root));config_path=Path('docs/baselines/b0/config-sample-v5.json');config_path.write_text(json.dumps(config,indent=2)+'\n')
registry=json.loads(Path('docs/baselines/b0/datasets-v1.json').read_text());datasets={}
for name,entry in registry.items():
 with Path(entry['path']).open() as f:corpus=[json.loads(s) for s in f if s.strip()]
 if name not in ('dulemon_gold','ecd_negative'):corpus=[x for x in corpus if x['questions']]
 random.Random(config['seed']).shuffle(corpus);chosen=corpus[:config['conversations_per_dataset'][name]]
 selected_questions=[]
 for c in chosen:
  questions=list(c['questions']);random.Random(config['seed']).shuffle(questions);selected_questions.extend(questions[:config['questions_per_conversation']])
 chunks=sum(math.ceil(len(d['text'])/4000) for c in chosen for d in c['documents']);queries=sum(min(len(c['questions']),config['questions_per_conversation']) for c in chosen)
 datasets[name]={'selected_dev_conversations':len(chosen),'complete_source_documents':sum(len(c['documents']) for c in chosen),'source_chunks':chunks,'selected_questions':queries,'question_categories':dict(collections.Counter(q['category'] for q in selected_questions)),'prepared_answer_rows_3repeats_2modes_4systems':queries*24,'extraction_source_event_upper_estimate_3repeats':chunks*3,'embedding_attempt_upper_estimate':chunks*12+queries*18,'tokenization_attempt_estimate':queries*6}
# Source jobs can be rejected by frozen input policy; extraction can emit 0..3 memories.
counts={'extraction':sum(x['extraction_source_event_upper_estimate_3repeats'] for x in datasets.values()),'embedding':sum(x['embedding_attempt_upper_estimate'] for x in datasets.values()),'answer':sum(x['prepared_answer_rows_3repeats_2modes_4systems'] for x in datasets.values()),'judge':sum(x['prepared_answer_rows_3repeats_2modes_4systems'] for x in datasets.values()),'tokenizer':sum(x['tokenization_attempt_estimate'] for x in datasets.values())}
report={'basis':'actual API lite pilot; not a price or available-balance quote','pilot_status':json.loads((root/'status.json').read_text()),'pilot_measured_by_role':roles,'selected_configuration':str(config_path),'sampling_decision':'fixed seeded sample; no performance-based or answer-based selection, complete source histories; no per-type representativeness claim','datasets':datasets,'approximate_upper_attempts_before_retries_or_failover':counts,'approximate_tokens_using_pilot_role_means':{role:count*roles[role]['mean_reported_tokens'] if role in roles and roles[role]['mean_reported_tokens'] is not None else None for role,count in counts.items()},'limitations':['source length and model output differ across datasets: pilot mean is a planning approximation, not measured future usage','embedding bound allows 3 extracted memories per event and query calls; genuine replay and rejected inputs may reduce new HTTP','tokenizer usage not reported, never costed as zero','format failure and retries/failover add calls; calibration cross-reference adds up to300 calls','all dev data hashes and source splits unchanged; omitted dev rows and unseen types are not claimed measured']}
Path('docs/baselines/b0/replacement-sample-budget-v1.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'actual_pilot':roles,'selected_counts':counts,'config':str(config_path)}))
