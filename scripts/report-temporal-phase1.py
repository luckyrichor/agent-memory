"""Generate public counts from restricted outputs, never publish source/candidates."""
import difflib, json, math, platform, re, subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from agent_memory.evals.evidence_v3 import sha
ROOT=Path('.local/phase1/round3/temporal-v1')
OUT=Path('docs/reports/phase1-round3-temporal-2026-10-22')

def load(p):return json.loads(p.read_text())
def main():
 OUT.mkdir(parents=True,exist_ok=True)
 screen=load(ROOT/'screen/report.json') if (ROOT/'screen/report.json').exists() else load(ROOT/'screen/manifest.json')
 pointer=load(ROOT/'increment-current.json') if (ROOT/'increment-current.json').exists() else None
 increment_root=Path(pointer['root']) if pointer else ROOT/'increment'
 batch_registry=increment_root/'batch-registry.json'
 batches=load(batch_registry) if batch_registry.exists() else [load(p) for p in sorted(increment_root.glob('batch-*/report.json'))]
 state=load(increment_root/'state.json') if (increment_root/'state.json').exists() else {}
 batch_paths=[Path(r['path']) for r in batches if 'path' in r]
 if state.get('active_batch_path') and Path(state['active_batch_path']) not in batch_paths:batch_paths.append(Path(state['active_batch_path']))
 if not batch_paths:batch_paths=sorted(increment_root.glob('batch-*'))
 schema_probe=load(ROOT/'json-schema-probe-v1/report.json') if (ROOT/'json-schema-probe-v1/report.json').exists() else None
 packet_probe=load(ROOT/'packet-size-probe-v1/report.json') if (ROOT/'packet-size-probe-v1/report.json').exists() else None
 single_packet=load(ROOT/'single-packet-real-controls-v1/report.json') if (ROOT/'single-packet-real-controls-v1/report.json').exists() else None
 cache_incident=load(ROOT/'cache-refresh-incident.json') if (ROOT/'cache-refresh-incident.json').exists() else None
 ecd=load(ROOT/'ecd-owner/report.json') if (ROOT/'ecd-owner/report.json').exists() else None
 if ecd:
  Path('docs/evals/ecd-human-current.json').write_text(json.dumps(ecd,ensure_ascii=False,indent=2)+'\n')
 positive_labels=ROOT/'human-positive-labels.jsonl';positive_items=ROOT/'human-positive-items.jsonl'
 registry={'basis':'owner-confirmed-subset-only','whole_joint_pool_accepted':False,'confirmed_positive_points':screen['deduplicated_human_positive'],
  'labels':{'path':str(positive_labels),'sha256':sha(positive_labels)},'items':{'path':str(positive_items),'sha256':sha(positive_items)},
  'new_owner_return_sha256':sha(Path('.local/dulemon72-v3-final-20261022.csv')),'phase1_accepted':False}
 Path('docs/evals/human-confirmed-current.json').write_text(json.dumps(registry,ensure_ascii=False,indent=2)+'\n')
 final=load(increment_root/'report.json') if (increment_root/'report.json').exists() else None
 usage=[];seen_calls=set()
 transport_records=[load(p) for p in sorted((ROOT/'transport-retries').glob('*/ledger.json'))]
 transport_extra_attempts=sum(len(r['attempts'])-(1 if r['attempts'] and r['attempts'][-1].get('accepted_by_transport') else 0) for r in transport_records)
 transport_extra_tokens=sum((a.get('usage') or {}).get('total_tokens',0) for r in transport_records for a in (r['attempts'][:-1] if r['attempts'] and r['attempts'][-1].get('accepted_by_transport') else r['attempts']))
 for p in sorted(ROOT.glob('**/ledger.json')):
  if 'transport-retries' in p.parts:continue
  history=load(p)
  if 'failed-before-strict-retry' in p.parts:history=history[-1:]
  for r in history:
   identity=(r['requested_model'],r['timestamp'],r.get('request_sha256'),r.get('offset'))
   if identity in seen_calls:continue
   seen_calls.add(identity)
   usage.append({'ledger':str(p),'model':r['requested_model'],'provider':r['provider'],'items':r['items'],
    'http':r.get('http'),'status':r['status'],'timestamp':r['timestamp'],'attempts':len(r.get('attempts',[])),
    'usage':r.get('usage'),'prompt_sha256':r['prompt_sha256'],'returned_model':r.get('returned_model')})
 plan=Path('docs/plans/2026-10-22-agent-memory-interview-plan-v3.md');old=Path('docs/plans/2026-10-21-agent-memory-interview-plan-v2.md')
 diff=''.join(difflib.unified_diff(old.read_text().splitlines(True),plan.read_text().splitlines(True),fromfile=str(old),tofile=str(plan)))
 (OUT/'plan-diff.patch').write_text(diff)
 code=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
 dirty=bool(subprocess.check_output(['git','status','--porcelain'],text=True).strip())
 models=screen.get('active_models',screen['models'])
 increment_manifest=load(increment_root/'manifest.json') if (increment_root/'manifest.json').exists() else {}
 increment_models=sorted({model for batch in batches for model in batch.get('models',[])}) or increment_manifest.get('models',models)
 # Original evidence remains DeepSeek+Tencent; screening adds replacement vendor when used.
 vendors={'deepseek-v4.1-flash-1017':'DeepSeek','hy4-preview':'Tencent','glm-5-2-260617':'Zhipu'}
 def vendor(x):
  if x.startswith('deepseek'):return 'DeepSeek'
  if x.startswith(('hy','hunyuan','youtu')):return 'Tencent'
  if x.startswith('glm'):return 'Zhipu'
  if x.startswith('mimo'):return 'Xiaomi'
  if x.startswith('minimax'):return 'MiniMax'
  if x.startswith('kimi'):return 'Moonshot'
  return vendors.get(x,x)
 actual_annotation_vendors=sorted({'DeepSeek','Tencent'}|{vendor(x) for x in models})
 blocked_judge_vendors=sorted(set(actual_annotation_vendors)|{'ByteDance'})
 judge={'old_pool_including_screening_annotation_vendors':actual_annotation_vendors,'answer_vendor':'ByteDance',
  'old_pool_excluded_judge_vendors':blocked_judge_vendors,
  'increment_annotation_vendors':sorted({vendor(x) for x in increment_models}),'increment_models':increment_models,
  'increment_vendor_independent_historically_preflighted_judge_vendors':['Zhipu'] if not any(vendor(x)=='Zhipu' for x in increment_models) else [],
  'increment_currently_available_qualified_judge_vendors':[],'increment_vendor_independent_options_not_necessarily_qualified':['Zhipu','Xiaomi','MiniMax','Moonshot'],
  'latest_availability_issue':'Ark GLM SetLimitExceeded during actual increment; Tencent GLM current full-schema control on 2026-10-22 also HTTP402/code401008; no formal judge scoring calls made',
  'old_pool_qualified_available_judges':[],'qualified_backup_count':0,'required_backups':1,'backup_gap':1,
  'main_judge_missing':True,'note':'Old265 pool uses GLM temporal screening, so Zhipu cannot judge that pool. New increment uses DeepSeek+Tencent and may use Zhipu by vendor independence, but Ark GLM hit SetLimitExceeded this run; Tencent GLM on 2026-10-22 again HTTP402/code401008. No currently available qualified judge is asserted. Other listed vendor-independent options are not technical qualification; human calibration remains incomplete.'}
 reserve=load(Path('.local/phase1/round3/pool-refresh-v3-v3/reserve-summary.json'))
 selected_dialogues=set();selected_candidates=set()
 for path in ROOT.glob('increment*/**/items.jsonl'):
  if not path.parent.name.startswith('batch-'):continue
  for line in path.read_text().splitlines():
   row=json.loads(line);selected_dialogues.add(row['conversation_id']);selected_candidates.add(row['item_id'])
 remaining_inventory={'eligible_unused_before_increment':reserve['available_field_valid_unique'],'unique_dialogues_selected_in_any_increment_attempt':len(selected_dialogues),'unused_not_selected_remaining':reserve['available_field_valid_unique']-len(selected_dialogues),'selected_candidate_slots':len(selected_candidates),'unfinished_selected_batches_not_claimed_unused':True,'selected_not_in_complete_batches':len(selected_dialogues)-sum(r['conversations'] for r in batches)}
 previous_yield=load(Path('.local/phase1/round3/tokenhub-pool-v4/deepseek-v4.1-flash-1017/yield-summary.json'))
 survival=previous_yield['joint_retention']*screen.get('pool_surviving_after_temporal_and_owner_rejection',screen['pool'])/screen['pool']
 target=max(72,700-screen['deduplicated_human_positive']+3)
 projected_candidates=math.ceil(target/survival)
 projected_dialogues=math.ceil(projected_candidates/reserve['candidates_per_available_dialogue'])
 projection={'target_joint_survivors':target,'historical_joint_rate':previous_yield['joint_retention'],
  'temporal_pool_survival_rate':screen.get('pool_surviving_after_temporal_and_owner_rejection',screen['pool'])/screen['pool'],
  'estimated_joint_rate':survival,'candidate_estimate':projected_candidates,'dialogue_estimate':projected_dialogues,
  'post_call_estimate_both_models':2*math.ceil(projected_candidates/8),
  'assumption_only':True,'not_a_claim_of_reliable_points':True,'reserve_before_increment':reserve['available_field_valid_unique']}
 model_observations=[]
 for batch_path in batch_paths:
  if not (batch_path/'manifest.json').exists():continue
  bm=load(batch_path/'manifest.json')
  for model in bm['models']:
   predictions=[json.loads(line) for shard in sorted(batch_path.glob('shard-*')) for p in sorted((shard/model.replace('/','-')).glob('*-checked.jsonl')) for line in p.read_text().splitlines() if line]
   model_observations.append({'batch':bm['batch'],'model':model,'expected':bm['candidates'],'completed':len(predictions),'keep':sum(r['label']=='keep' for r in predictions),'temporary':sum(r['temporal']=='临时' for r in predictions),'citation_invalid':sum(not r['citation_valid'] for r in predictions)})
 completed_one_side=next((r for r in model_observations if r['completed']==r['expected'] and r['keep']>0),None)
 if completed_one_side:
  one_rate=completed_one_side['keep']/completed_one_side['completed']
  optimistic_candidates=math.ceil(target/one_rate);optimistic_dialogues=math.ceil(optimistic_candidates/reserve['candidates_per_available_dialogue'])
  projection.update(previous_preselected_pool_projection_retired=True,correction_reason='preselected701 pool survival does not represent raw new candidate yield',
   observed_single_side=completed_one_side,optimistic_joint_rate_assumption=one_rate,
   optimistic_candidate_estimate=optimistic_candidates,optimistic_dialogue_estimate=optimistic_dialogues,
   optimistic_post_call_estimate=2*math.ceil(optimistic_candidates/8),
   joint_precision_or_yield_unknown_until_both_sides_complete=True)
  retired={k:projection[k] for k in ('candidate_estimate','dialogue_estimate','post_call_estimate_both_models','estimated_joint_rate')}
  projection.update(retired_preselected_projection=retired,candidate_estimate=optimistic_candidates,dialogue_estimate=optimistic_dialogues,post_call_estimate_both_models=2*math.ceil(optimistic_candidates/8),estimated_joint_rate=one_rate,estimate_kind='optimistic conditional single-side extrapolation, not observed joint yield')
 if batches:
  observed_n=sum(r['candidates'] for r in batches);observed_k=sum(r['joint_keep'] for r in batches)
  if observed_k:
   joint_rate=observed_k/observed_n;needed=math.ceil(target/joint_rate)
   projection.update(observed_joint_keep=observed_k,observed_joint_candidates=observed_n,joint_precision_or_yield_unknown_until_both_sides_complete=False,estimated_joint_rate=joint_rate,
    candidate_estimate=needed,dialogue_estimate=math.ceil(needed/reserve['candidates_per_available_dialogue']),
    post_call_estimate_both_models=2*math.ceil(needed/8),estimate_kind='conditional completed-batch joint yield extrapolation; not quality or adopted count')
 if batches:
  remaining=max(0,target-(final['joint_keep'] if final else sum(r['joint_keep'] for r in batches)));rate=projection['estimated_joint_rate'];needed=math.ceil(remaining/rate) if rate else None
  projection.update(remaining_joint_target=remaining,remaining_candidate_estimate=needed,remaining_dialogue_estimate=math.ceil(needed/reserve['candidates_per_available_dialogue']) if needed else 0,remaining_post_estimate_two_sides_at_batch8=2*math.ceil(needed/8) if needed else 0,executable_model_pair_currently_available=None,assumption='future fully qualified pair must become available; observed yield may not transfer to another pair; no capacity or quality claim')
 if single_packet and single_packet['all_format_and_quote_checks_passed']:
  total=projection['candidate_estimate'];remaining=projection.get('remaining_candidate_estimate',max(0,total-sum(r['candidates'] for r in batches)))
  packet_models=('deepseek/deepseek-v4-flash-vision-exp','hunyuan-turbos-vision-video-20250728')
  averages={}
  for model in packet_models:
   records=[r for r in usage if r['model']==model and r['status']=='complete' and r['attempts'] and r['usage'] and (model!=packet_models[1] or r['items']==1)]
   points=sum(r['items'] for r in records);tokens=sum(r['usage'].get('total_tokens',0) for r in records)
   averages[model]={'observed_requests':len(records),'observed_candidate_items':points,'reported_tokens':tokens,'mean_tokens_per_item':tokens/points if points else None}
  projection.update(transport_packet_sizes={packet_models[0]:8,packet_models[1]:1},single_packet_complete_candidate_call_estimate=math.ceil(total/8)+total,single_packet_remaining_candidate_call_estimate=math.ceil(remaining/8)+remaining,single_packet_observed_token_means=averages,quota_sufficiency_not_inferred=True)
  if all(r['mean_tokens_per_item'] is not None for r in averages.values()):projection['single_packet_remaining_tokens_conditional_estimate']=math.ceil(remaining*sum(r['mean_tokens_per_item'] for r in averages.values()))
 adoption=None
 if (ROOT/'screen/proposed-survivors-private.jsonl').exists():
  proposed={json.loads(x)['item_id'] for x in (ROOT/'screen/proposed-survivors-private.jsonl').read_text().splitlines()}
  confirmed={json.loads(x)['item_id'] for x in (ROOT/'human-positive-labels.jsonl').read_text().splitlines()}
  adoption={'human_confirmed':len(confirmed),'screened_model_pool':len(proposed),'overlap_human_and_screened_pool':len(proposed&confirmed),
   'not_individually_reviewed_model_survivors':len(proposed-confirmed),'union_if_owner_adopts_and_human_labels_authoritative':len(proposed|confirmed),
   'actual_adopted_model_unreviewed':0,'owner_decision_pending':True}
 qualifications=[load(p) for p in sorted(Path('.local/phase1/round3/tokenhub-pool-qualification').glob('*/report.json')) if p.parent.name!='deepseek-v4.1-flash-1017']
 repaired_qualifications=[load(p) for p in sorted(Path('.local/phase1/round3/tokenhub-pool-qualification-throttled-v1').glob('*/report.json'))]
 diverse_qualifications=[load(p) for p in sorted((ROOT/'diverse-annotation-qualification').glob('*/report.json'))]
 full_qualifications=[load(p) for p in sorted((ROOT/'full-annotation-qualification').glob('*/report.json'))]
 interrupted_qualification=[load(p) for p in sorted((ROOT/'annotation-qualification').glob('*/interrupted-summary.json'))]
 qualification_known_attempts=sum(x['calls'] for x in qualifications)+sum(x['new_post_attempts'] for x in repaired_qualifications+diverse_qualifications)+sum(x['calls'] for x in full_qualifications)+sum(x['saved_responses'] for x in interrupted_qualification)
 qualification_unknown_attempts=sum(x.get('interrupted_request_usage_unknown',0) for x in interrupted_qualification)+sum(x.get('potential_interrupted_request_usage_unknown',0) for x in full_qualifications)
 qualification_tokens=sum(x.get('reported_tokens',0) for x in qualifications+full_qualifications+interrupted_qualification)+sum(x.get('new_reported_tokens',0) for x in repaired_qualifications+diverse_qualifications)
 outgoing=load(increment_root/'outgoing-verification.json') if (increment_root/'outgoing-verification.json').exists() else None
 validation_path=ROOT/'check-final.log'
 validation_text=validation_path.read_text()
 test_match=re.search(r'(\d+) passed in ([\d.]+)s',validation_text)
 type_match=re.search(r'no issues found in (\d+) source files',validation_text)
 validation={'pytest_passed':int(test_match[1]) if test_match else None,'pytest_seconds':float(test_match[2]) if test_match else None,
  'ruff_passed':'All checks passed!' in validation_text,'strict_mypy_source_files':int(type_match[1]) if type_match else None,
  'foundation_passed':'total=8 passed=8 failed=0 tenant_leaks=0 deleted_memory_hits=0' in validation_text,'log_sha256':sha(validation_path)}
 report={'generated_at':datetime.now(timezone.utc).isoformat(),'code_commit':code,'tracked_changes':dirty,'python':platform.python_version(),
  'plan':{'path':str(plan),'sha256':sha(plan),'previous_sha256':sha(old),'source_message_id':'om_x100b62ae48d290b8dd72c5b51feec54',
  'execution':'latest plan plus latest explicit owner temporal/audit instructions; phase1 only',
  'changes':['新增PAL-Set：阶段2之后可选，不计入阶段1金标或召回','新增两层记忆设计：阶段1只做长期记忆；短期TTL以后可选，本轮未实现','额度不足可自动替换标注模型；受影响侧按冻结批整批重标，旧标签留历史不混用'],
  'remaining_internal_conflicts':['旧角色表写两个备选，与负责人后续至少一个不一致，按后续至少一个执行','旧角色表仍列DeepSeek/MiMo，实际采用负责人已授权的替代组合，按每批来源记录','原生22/旧711属于历史规模，当前使用真实回填及当前登记，不沿用旧总数']},
  'current_candidate_catalog':load(ROOT/'candidate-current-status.json') if (ROOT/'candidate-current-status.json').exists() else None,'json_schema_api_probe':schema_probe,'packet_size_transport_probe':packet_probe,'single_packet_actual_controls':single_packet,'private_audit_structure_verification':outgoing,'cache_refresh_incident':cache_incident,'remaining_source_inventory':remaining_inventory,'adoption_projection':adoption,'partial_model_observations':model_observations,'production_projection':projection,'validation':validation,'screen':screen,'ecd':ecd,'increment':final or {'complete':False,'batches':batches,'new_points_adopted':0},'increment_switches':pointer.get('switches',[]) if pointer else [],'judge':judge,
  'new_replacement_qualification':qualifications,'ordinary429_repaired_qualification':repaired_qualifications,'diverse_full_schema_qualification':diverse_qualifications,'full_schema_qualification':full_qualifications,'retired_repeated_probe':interrupted_qualification,
  'calls':{'qualification_attempts':qualification_known_attempts,'qualification_potential_inflight_without_response':qualification_unknown_attempts,'qualification_attempts_upper_bound':qualification_known_attempts+qualification_unknown_attempts,'qualification_reported_tokens':qualification_tokens,'transport_extra_attempts':transport_extra_attempts,'transport_schema_invalid_attempts':sum(a.get('error_type')=='ValidationError' for r in transport_records for a in r['attempts']),'post_attempts':sum(r['attempts'] for r in usage)+transport_extra_attempts,'reported_tokens':sum((r['usage'] or {}).get('total_tokens',0) for r in usage)+transport_extra_tokens,'unique_ledger_records_by_model':dict(Counter(r['model'] for r in usage)),'post_attempts_by_model':{m:sum(r['attempts'] for r in usage if r['model']==m) for m in sorted({r['model'] for r in usage})},'potential_inflight_without_response':sum(r['status']=='started' and r['attempts']==0 for r in usage),'genuine_cached_response_replays':sum(r['attempts']==0 and r['status']=='complete' for r in usage)},
  'private_evidence_hashes':{str(p):sha(p) for p in sorted(ROOT.glob('**/*.json')) if p.name in ('manifest.json','report.json','ledger.json')},
  'phase1_accepted':False,'owner_adoption_decision_pending':True,'increment_runtime_state':state,
  'unfinished':['旧池时效性筛选是否采用，等待负责人决定','补量被额度及真实批量格式故障阻塞；未达新增目标；本地阶段性盲审未发，补量完成后再交' if final and final.get('audit_prepared_private_only') else '新增独立72盲审等待负责人核对' if final and final.get('audit') else '增量标注或审核表导出未完成','当前可用裁判主备与人工校准仍有缺口','完整负样本会话数与负样本比例两个闸门尚未共同确认','ECD只完成真实回填接入；系统误抽评测未运行']}
 schema_probe_calls=schema_probe.get('calls',0) if schema_probe else 0
 schema_probe_tokens=(schema_probe.get('usage') or {}).get('total_tokens',0) if schema_probe else 0
 report['calls'].update(transport_schema_probe_calls=schema_probe_calls,transport_schema_probe_reported_tokens=schema_probe_tokens)
 report['calls'].update(total_known_post_attempts=schema_probe_calls+report['calls']['post_attempts']+qualification_known_attempts,total_potential_unknown_requests=report['calls']['potential_inflight_without_response']+qualification_unknown_attempts,total_reported_tokens=report['calls']['reported_tokens']+qualification_tokens+schema_probe_tokens,catalog_gets=1 if (ROOT/'candidate-current-status.json').exists() else 0)
 (OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
 estimate=screen['audit_precision'];lo,hi=estimate['ci95'];text=[
 '# agent-memory 阶段1：长期记忆筛选与补量交接',
 f"生成时间：{report['generated_at']}；代码：{code}；生成前存在未提交改动（含新文件）：{dirty}。阶段1仍未验收，不进入阶段2。",
 f"执行方案：`{plan}`；SHA256 `{sha(plan)}`。原作者保留，旧版未覆盖。按最新方案及负责人当前任务执行。",
 '## 方案变化与口径',*['- '+x for x in report['plan']['changes']],*['- 内部旧口径：'+x for x in report['plan']['remaining_internal_conflicts']],
 '完整逐行差异见 plan-diff.patch。PAL-Set来源内容为负责人方案声明，本轮未另行验证或下载。',
 '## 新盲审与人工正例',
 f"精度 {int(estimate['numerator'])}/{int(estimate['denominator'])} = {100*estimate['value']:.4f}%；按会话聚类，{estimate['n']}个会话，1000次重采样、种子42，95%区间 [{100*lo:.4f}%, {100*hi:.4f}%]。",
 f"错误 {screen['audit_errors']} 条，上限 {screen['maximum_errors']} 条，压线通过。错误类型：临时状态误作长期记忆 {screen['error_types']['temporary-state-as-long-term']} 条。置信区间不是新的通过门。",
 f"逐条人工确认：此前 {screen['old_positive']} + 本轮 {screen['new_positive']}，按原item_id去重 {screen['deduplicated_human_positive']}；这些是人工正例，不是整池逐条人工核验。",
 f"仅按人工确认规模，到700缺 {max(0,700-screen['deduplicated_human_positive'])}；到1500缺 {max(0,1500-screen['deduplicated_human_positive'])}。原265池与本轮72重叠，不能再把72加一次。",
 '## 时效性筛选（待负责人决定是否采用）',
 f"原池 {screen['pool']}，与历史正例合并后仅判时效性的输入 {screen['items']}；模型：{', '.join(models)}。提示词只新增时效性标准，例子完全虚构，候选不改写。原引用校验器不变。",
 'HY4在完成部分后HTTP402，停止旧侧；替代模型对该侧全部输入重新判定，旧部分不混用。腾讯HY3额度不足；HY-role首轮因普通429未完成预检，后续仅补齐被限流的同一虚构请求，结果见下方资格台账，不混淆格式错误与限流。详见私有switches/ledger。',
 ]
 if 'known_errors_identified' in screen:
  text += [f"已知临时错误识别 {screen['known_errors_identified']}/{screen['known_errors_denominator']}；人工正确项误剔除 {screen['human_positive_falsely_removed']}/{screen['human_positive_denominator']}（此前85中 {screen['previous85_falsely_removed']}，本轮69中 {screen['new69_falsely_removed']}）。",
   f"原池时效性剔除 {screen['pool_temporary_removed']}；人工判错显式扣除 {screen['known_errors_explicitly_removed']}，两类取并集，不重复扣。筛后拟采纳池 {adoption['screened_model_pool']}，其中已人工确认{adoption['overlap_human_and_screened_pool']}、尚未逐条人工核验{adoption['not_individually_reviewed_model_survivors']}。如负责人采用且人工标签保持权威，与全部人工正例去重并集为{adoption['union_if_owner_adopts_and_human_labels_authoritative']}；当前实际模型池采纳仍为{adoption['actual_adopted_model_unreviewed']}。早期301仅是216与此前85相加，漏含筛选误剔除但本轮已人工确认的9项，不作为总体可靠规模。",
   '人工确认登记不由模型误剔除自动改写；模型筛选池与人工登记分别保存。没有自行设置筛选通过线。']
 text += ['## 增量批次',f"源对话库存：补量开始前有{remaining_inventory['eligible_unused_before_increment']}段未用且字段完整对话；包括未完成/退役尝试在内，按会话ID去重已选{remaining_inventory['unique_dialogues_selected_in_any_increment_attempt']}段，尚未选入任何补量批次{remaining_inventory['unused_not_selected_remaining']}段。控制器remaining_unused_dialogues只减完成批，不将其冒称真实未用库存。",'每100段固定对话为一个冻结批次；额度切换时当前批受影响一侧整批重标，已完成批保留独立模型来源，不拼接半批。此口径在首个增量批完成前确定，替代此前全部队列重启方式。格式无效条目严格拒绝并记程序uncertain，不删多余字段、不修改响应、不放宽引用校验；程序uncertain不作模型语义判断或一致率证据。时效性剔除为任一侧标临时的条目数，包含本已discard/uncertain项，与引用、结构无效计数可重叠，不应相加。',('补量预算基于已完成批次的真实共同保留率，仍是条件外推。预筛池及两侧各8条/请求的旧预算留历史，当前腾讯单条请求另算调用数与token；不能据此推断账户余额。' if completed_one_side else f"补量预算（条件估算，非实际产出）：以历史共同保留率和本轮时效性幸存率相乘约{100*survival:.2f}%估算，需{target}个新共同保留候选（不依赖旧池待批采纳），预计{projected_candidates}个候选、{projected_dialogues}段对话、双模型约{projection['post_call_estimate_both_models']}次POST；更换模型/整百对话批次舍入会增加实际调用。抽样前可用对话{reserve['available_field_valid_unique']}段。"),'固定新种子；只用未用过且字段完整的BOTH/train，沿用原候选生成逻辑，原生标签字段不提供给模型。继承原会话切分。新增池在负责人独立72盲审前不计入可靠规模。',
 '|批次|模型组合|完整对话分母|候选|共同保留|临时标记/排除（任一侧）|引用无效（任一侧）|结构无效|','|---|---|---:|---:|---:|---:|---:|---:|']
 text += [f"|{r['batch']}|{' + '.join(r.get('models',[]))}|{r['conversations']}|{r['candidates']}|{r['joint_keep']}|{r['temporal_removed']}|{r['citation_invalid']}|{r.get('schema_invalid','未单列')}|" for r in batches]
 if final and final.get('audit') and final.get('audit_prepared_private_only'):text += [f"已完整冻结{final['conversations']}段/{final['candidates']}候选，共同保留{final['joint_keep']}；新增目标{final['target_unreviewed_joint_keeps']}未达到，尚缺{final['unresolved_target_joint_keeps']}。失败的当前批整体排除，实际新增采纳{final['new_points_adopted']}。阶段性{final['audit']['sample']}条审核包仅本地准备、未发出、不作为人工证据；遵守补量完成后再发新增盲审表的顺序，不催本次临时包。",f"阻塞：{json.dumps({k:v for k,v in final['blocked'].items() if k!='observations'},ensure_ascii=False)}。已终止本次运行，不是补量完成或阶段验收；有界候选试用结果不代表所有目录型号都不可用。"]
 elif final and final.get('audit'):text += [f"新增共 {final['conversations']} 段/{final['candidates']}候选，共同保留 {final['joint_keep']}。独立审核表 {final['audit']['sample']}条，新种子{final['audit']['seed']}，历史审核条目重叠 {final['audit']['previous_review_overlap']}。新增实际采纳 {final['new_points_adopted']}，等待负责人审核≤3错。"]
 else:text+=['补量未完成；未宣称达到700或1500。',f"实际单侧进度（不是共同保留，不计可靠规模）：{json.dumps(model_observations,ensure_ascii=False)}",f"当前阻塞记录：{json.dumps((final or {}).get('blocked'),ensure_ascii=False)}；具体完成状态：{(final or {}).get('complete',False)}。"]
 if completed_one_side:
  text += [f"预算更正：早期按预筛701池外推原始候选不合适，已退役该估计。当前完整单侧保留{completed_one_side['keep']}/{completed_one_side['completed']}；如果另一侧不再损失任何候选，条件乐观外推需{optimistic_candidates}候选、{optimistic_dialogues}对话、约{projection['optimistic_post_call_estimate']}次双侧POST。该单侧口径不能当作实际共同保留率或产出承诺；不设新产量质量门。"]
 if batches:
  text += [f"按已完成批次条件外推：{projection['observed_joint_keep']}/{projection['observed_joint_candidates']}共同保留，若后续同分布，预计{projection['candidate_estimate']}候选、{projection['dialogue_estimate']}对话、双侧{projection['post_call_estimate_both_models']}次POST产生目标{target}条；未含重试/换型重标/百会话舍入，不是实际可靠规模。"]
 if ecd:
  text += ['## ECD负样本小金标准',f"标注方式：**{ecd['annotation_method']}**，不是人工独立标注；Agent未改任何人工标签。全表{ecd['conversations']}段：无应记内容{ecd['counts']['negative']}段（{100*ecd['negative_fraction_all_conversations']:.2f}%，分母{ecd['negative_fraction_denominator']}）；有应记内容{ecd['counts']['positive']}段；不确定{ecd['counts']['uncertain']}段单列，不计正负。",'冻结非人工字段逐项核对一致，旧120表未覆盖。108段作为已确认负样本小金标准；7段正会话不自动折算为7个DuLeMon记忆点。不代表ECD总体分布，尚未用系统运行误抽评测。原文、审核理由与应记内容仅服务器.local/，对外只方法、哈希、指标。',f"回填SHA256：`{ecd['submitted_sha256']}`。"]
 text += ['## 裁判池影响','|数据表|实际标注或筛选厂商|答题厂商|当前可调用且合格裁判厂商|主备缺口|','|---|---|---|---|---|',f"|旧池含时效性筛选|{'、'.join(actual_annotation_vendors)}|ByteDance|无已验证可用|主裁判缺失，备选缺{judge['backup_gap']}|",f"|新增已完成批|{'、'.join(judge['increment_annotation_vendors'])}|ByteDance|无已验证可用；Zhipu仅满足厂商独立|主裁判缺失，备选缺{judge['backup_gap']}|",'标注模型逐批列在report.json；Xiaomi、MiniMax、Moonshot仅是未触犯厂商排除的候选范围，不代表预检或实际调用合格。腾讯GLM本轮实际402，Ark GLM本轮用量上限，未以目录online代替可调用证据。','旧池时效性筛选实际用过GLM，因此旧池不能由智谱裁判；新补量若最终仅用DeepSeek/腾讯，智谱在厂商独立性上可用，历史预检也通过，但Ark本轮已SetLimitExceeded，不能称当前可用。原GLM部分补量结果已退役，不混入新批。当前稳定可用主裁判缺失，备用仍缺至少一个；未放宽预检，人工校准也未完成。',
 '## 用量与证据',f"完整门禁：pytest {validation['pytest_passed']}通过/{validation['pytest_seconds']}秒，ruff通过={validation['ruff_passed']}，strict mypy {validation['strict_mypy_source_files']}源文件，foundation零泄漏门通过={validation['foundation_passed']}。原始日志见validation.log。",f"当前台账POST尝试 {report['calls']['post_attempts']}；成功响应报告token {report['calls']['reported_tokens']}。另有{report['calls']['potential_inflight_without_response']}条可能在途、没有最终响应记录；失败或中断无usage不按0实际用量推断，以上为响应报告token而非完整账单。额外替代资格预检台账在tokenhub-pool-qualification目录，单独记录，未混为筛选调用。",
 f"替代资格预检已知POST尝试{report['calls']['qualification_attempts']}次，另{report['calls']['qualification_potential_inflight_without_response']}次可能在途，报告token合计{report['calls']['qualification_reported_tokens']}；普通429与额度故障分开。旧报告不覆盖，Ark历史预检复用不计新调用。各次资格结果见下表及report.json，不与真实人工质量校验混淆。",
 '原始CSV、来源、请求响应、映射、调用台账只在服务器.local/，公开仓库仅方法、哈希、指标。CSV SHA256：`'+sha(Path('.local/dulemon72-v3-final-20261022.csv'))+'`。',
 '重放汇总：`uv run python scripts/report-temporal-phase1.py`；真实筛选入口：`scripts/continue-temporal-screen.py`；多候选旧入口v4已经关闭并保留历史；当前单条请求入口：`scripts/run-temporal-batch-cohorts-v5.py`，候选/提示词/引用校验不变；旧阻塞快照由`scripts/finalize-temporal-completed-batches.py`保留，不覆盖新批。缓存修复后只复用真实响应并重验；修复前实际重复调用仍在事故台账中，不声称没有多计费。',
 '### 技术预检台账（不是人工质量证据）',
 '|组别|模型|格式有效/检查数|五次判定一致|关闭思考检查|技术预检通过|已知新POST|响应报告token|','|---|---|---:|---|---|---|---:|---:|',
 *[f"|{group}|{r['model']}|{r.get('format_valid',0)}/{r.get('format_n',0)}|{r.get('consistent_5',False)}|{r.get('observed_disabled_thinking',False)}|{r.get('passed',False)}|{r.get('new_post_attempts',r.get('calls',0))}|{r.get('new_reported_tokens',r.get('reported_tokens',0))}|" for group,records in [('原始通用格式',qualifications),('限流同题补齐',repaired_qualifications),('完整v3修正预检',diverse_qualifications),('完整v3虚构预检',full_qualifications)] for r in records],
 '完整v3预检的五次一致指label与temporal判定一致，不声称证据说明逐字节相同；100不同输入用于格式控制，虚构内容只有长期/临时两类模板，不作为语义准确率证据。腾讯Turbo虚构单项预检通过，真实多候选根结构持续失败；另用真实控制确认单条请求格式后，独立版本恢复，不把格式通过冒充人工质量通过。',
 f"返工：早期虚构生成器只改变未进入实际请求的字段，重复探测不能算100不同输入；已停用并独立重做。旧结果和未知中断用量保留：{json.dumps(interrupted_qualification,ensure_ascii=False)}。", 
 f"缓存刷新返工：{json.dumps(cache_incident,ensure_ascii=False)}。旧索引在同进程换侧后未刷新，造成另一完整侧重复调用；发现后中断，独立新入口每侧开始前刷新真实响应索引并重新严格校验。事故台账区分重复的混元侧和本就需要新标的DeepSeek侧；中断无响应的usage未知，不当作零。不改原始台账。",
 '候选状态复核：当前目录仍标online的型号也可能实际402，不等于可调用。YT-VITA目录标discontinued，发现后中断其虚构预检，未进入标注池或裁判池；已发生调用与未知中断usage仍保留。没有以实际返回过200绕过退役状态或格式门槛。',
 f"后续预算仅条件估算：还需{projection.get('remaining_joint_target')}个未审共同保留候选；按完成批次留存率预计{projection.get('remaining_candidate_estimate')}候选、{projection.get('remaining_dialogue_estimate')}对话、按每请求8候选双侧约{projection.get('remaining_post_estimate_two_sides_at_batch8')}次POST，不含重试/换型。这是两侧都8条/请求的旧预算；若启用腾讯单条请求，以后面的新预算为准。换型或改调用分组后不承诺继承产率，不推断额度足够。",
 '### 单条请求修复与新预算',f"真实分组探测：{json.dumps(packet_probe,ensure_ascii=False)}；分散真实输入控制：{json.dumps(single_packet,ensure_ascii=False)}。仅验证格式/引用机械校验，不是语义质量证据。用于排查的真实条目保守排除出后续盲审及可采纳池；原多条请求不合格响应不修复、不混入。",f"当前分组预算：{json.dumps({k:v for k,v in projection.items() if k.startswith('single_packet') or k in ('transport_packet_sizes','quota_sufficiency_not_inferred')},ensure_ascii=False)}。token按真实单条调用小样本均值条件外推，完整来源长度不同会改变用量；调用数不含重试/换型，格式恢复不代表余额足够。运行状态以本报告increment字段为准。",
 f"API结构化输出虚构探测：{json.dumps(schema_probe,ensure_ascii=False)}。HTTP200不代表返回已满足原严格结构；失败包未进入任何标注池，不采用该方案；额外调用与token另记。",
 '## 未完成项',*['- '+x for x in report['unfinished']]]
 rendered='\n\n'.join(text)+'\n'
 rendered=re.sub(r'(?<=\|)\n\n(?=\|)','\n',rendered)
 (OUT/'delivery.md').write_text(rendered)
 print(json.dumps({'report':str(OUT),'phase1_accepted':False}))
if __name__=='__main__':main()
