"""Generate frozen rebuild profile, conservative vector allowance and historical exclusions."""
import hashlib,json,math,random
from collections import Counter
from pathlib import Path
from agent_memory.evals.b0_frozen import AUTH,BIAS

def load(p):return json.loads(Path(p).read_text())
def main():
 root=Path('.local/phase2/b0/frozen-deepseek-20261026-v1');out=Path('docs/reports/phase2-b0-rebuild-2026-10-26');out.mkdir(parents=True,exist_ok=True)
 cfg=load('docs/baselines/b0/config-sample-v9.json')
 for k in ('four_key_authorization','family_continuation_authorization','deepseek_last_resort_authorization','runtime_change_authorization'):cfg.pop(k,None)
 cfg.update(extraction_model='deepseek-v4-pro',extraction_provider='DeepSeek',answer_models=['deepseek-v4-pro'],answer_provider='DeepSeek',judge_model='glm-5.2',judge_models=['glm-5.2','minimax-m3'],judge_provider='TokenHub',cross_reference_model='minimax-m3',cross_reference_provider='TokenHub',embedding_model='kinfra-text-embedding-0.6b',embedding_provider='TokenHub',embedding_protocol='openai',resume_roots=[],embedding_cache_roots=[],frozen_b0_authorization=AUTH,baseline_configuration_id='B0-deepseek-v4-pro-kinfra-20261026-v1',expected_response_models={'answer':'deepseek-v4-pro','extraction':'deepseek-v4-pro'},calibration_seed=2026102601,conversation_concurrency=2,purpose='New B0 under owner-frozen single DeepSeek model and native Tencent1024 vectors; fresh index, all old results exploratory; no Ark calls',role_accounts={'extraction':{'DeepSeek':'deepseek-direct'},'answer':{'DeepSeek':'deepseek-direct'},'embedding':{'TokenHub':'tokenhub-secondary'},'judge':{'TokenHub':'tokenhub-secondary'},'cross-reference':{'TokenHub':'tokenhub-secondary'}})
 registry=load('docs/baselines/b0/datasets-v1.json');datasets={}
 for name,entry in registry.items():
  with Path(entry['path']).open() as f:corpus=[json.loads(s) for s in f if s.strip()]
  if name not in ('dulemon_gold','ecd_negative'):corpus=[c for c in corpus if c['questions']]
  random.Random(cfg['seed']).shuffle(corpus);selected=corpus[:cfg['conversations_per_dataset'][name]]
  chunks=sum(math.ceil(len(d['text'])/4000) for c in selected for d in c['documents']);questions=sum(min(len(c['questions']),cfg['questions_per_conversation']) for c in selected)
  # Per repetition: direct up to1 worker+1 raw baseline vector per chunk;
  # full up to3 candidate worker+3 baseline vector calls; three query embeddings per mode.
  datasets[name]={'conversations':len(selected),'chunks':chunks,'questions':questions,'answer_rows':questions*24,'source_extraction_calls':chunks*3,'conservative_vector_calls_before_retries':chunks*24+questions*18,'source_sha256':entry['sha256'],'selection_sha256':hashlib.sha256(json.dumps([c['conversation_id'] for c in selected]).encode()).hexdigest()}
 calls=sum(v['conservative_vector_calls_before_retries'] for v in datasets.values());reserved=math.ceil(calls*.25);cfg['embedding_call_budget']=calls+reserved
 profile=Path('docs/baselines/b0/config-frozen-deepseek-v1.json');profile.write_text(json.dumps(cfg,ensure_ascii=False,indent=2)+'\n')
 pilot={**cfg,'conversations_per_dataset':{'longmemeval_oracle':1},'questions_per_conversation':1,'embedding_call_budget':600,'purpose':'new configuration pilot on1 seeded dev conversation, two modes,3 repeats,4 systems; not full B0'}
 (root/'pilot-profile-private.json').write_text(json.dumps(pilot,ensure_ascii=False,indent=2)+'\n');(root/'pilot-profile-private.json').chmod(0o600)
 old=[]
 for p in Path('.local/phase2/b0').rglob('run-manifest.json'):
  m=load(p)
  if m.get('offline_fixture_only') or m.get('config',{}).get('frozen_b0_authorization')==AUTH:continue
  old.append({'run':str(p.parent),'classification':'探索性，不计入 B0','manifest_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'reason':'prior mixed answer models or superseded model/vector configuration'})
 (out/'historical-classification.json').write_text(json.dumps({'baseline_code_tag_unchanged':'B0','new_configuration_id':cfg['baseline_configuration_id'],'old_results':old,'old_calibration_tables':'superseded; do not reuse; new300 must sample only new completed run'},ensure_ascii=False,indent=2)+'\n')
 budget={'datasets':datasets,'answer_rows':sum(x['answer_rows'] for x in datasets.values()),'vector_calls_before_retries':calls,'reserve_fraction':.25,'reserved_vector_calls':reserved,'vector_call_budget':calls+reserved,'pilot_vector_budget':600,'total_planned_vector_allowance_including600pilot106preflight1length_probe':calls+reserved+600+106+1,'preflight_vector_trials':106,'estimated_extra_vector_character_limit_probes':1,'allowance_is_planning_not_provider_reservation':True,'balance_not_queried':True,'vector_model_auto_switch':False,'approximate_serial_seconds_at_1_2sec_pacing':(calls+reserved)*1.2,'new_vectors_only':True,'old_ark_vectors_reused':False,'old_answers_reused':False,'bias_limitation':BIAS,'O10':'new controlled Ark-vs-Tencent comparison not available because Ark quota exhausted; old measurements exploratory only, not new B0 comparator; no superiority claim'}
 (out/'vector-budget.json').write_text(json.dumps(budget,ensure_ascii=False,indent=2)+'\n')
 plan=Path('docs/plans/2026-10-26-agent-memory-interview-plan-v4.md')
 (out/'plan-update.json').write_text(json.dumps({'plan':str(plan),'sha256':hashlib.sha256(plan.read_bytes()).hexdigest(),'lines':len(plan.read_text().splitlines()),'read_completely':True,'change_from_previous':'8-line authoritative model-role update in section7; original author attribution preserved','frozen_code_tag':'B0','frozen_business_commit':'1e9d6f3b25b58c85792344000d7e1b5a71a79737','new_model_configuration':cfg['baseline_configuration_id'],'prior_owner_overrides_retained':['development only, test deferred','independent Linux load host not Mac','phase1 accepted union756/global828 and282ECD negative; AI drafts plus human confirmation'],'superseded':['same-family mixed answer/extraction continuation','Ark use','DeepSeek only as last resort'],'bias_limitation':BIAS},ensure_ascii=False,indent=2)+'\n')
 print(json.dumps({'vector_calls':calls,'reserve':reserved,'budget':cfg['embedding_call_budget'],'answer_rows':budget['answer_rows'],'old_exploratory_runs':len(old)}))
if __name__=='__main__':main()
