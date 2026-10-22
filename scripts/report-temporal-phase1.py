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
 batches=[load(p) for p in sorted(increment_root.glob('batch-*/report.json'))]
 ecd=load(ROOT/'ecd-owner/report.json') if (ROOT/'ecd-owner/report.json').exists() else None
 if ecd:
  Path('docs/evals/ecd-human-current.json').write_text(json.dumps(ecd,ensure_ascii=False,indent=2)+'\n')
 positive_labels=ROOT/'human-positive-labels.jsonl';positive_items=ROOT/'human-positive-items.jsonl'
 registry={'basis':'owner-confirmed-subset-only','whole_joint_pool_accepted':False,'confirmed_positive_points':screen['deduplicated_human_positive'],
  'labels':{'path':str(positive_labels),'sha256':sha(positive_labels)},'items':{'path':str(positive_items),'sha256':sha(positive_items)},
  'new_owner_return_sha256':sha(Path('.local/dulemon72-v3-final-20261022.csv')),'phase1_accepted':False}
 Path('docs/evals/human-confirmed-current.json').write_text(json.dumps(registry,ensure_ascii=False,indent=2)+'\n')
 final=load(increment_root/'report.json') if (increment_root/'report.json').exists() else None
 usage=[]
 for p in sorted(ROOT.glob('**/ledger.json')):
  for r in load(p):
   usage.append({'ledger':str(p),'model':r['requested_model'],'provider':r['provider'],'items':r['items'],
    'http':r.get('http'),'status':r['status'],'timestamp':r['timestamp'],'attempts':len(r.get('attempts',[])),
    'usage':r.get('usage'),'prompt_sha256':r['prompt_sha256'],'returned_model':r.get('returned_model')})
 plan=Path('docs/plans/2026-10-22-agent-memory-interview-plan-v3.md');old=Path('docs/plans/2026-10-21-agent-memory-interview-plan-v2.md')
 diff=''.join(difflib.unified_diff(old.read_text().splitlines(True),plan.read_text().splitlines(True),fromfile=str(old),tofile=str(plan)))
 (OUT/'plan-diff.patch').write_text(diff)
 code=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
 dirty=bool(subprocess.check_output(['git','status','--porcelain','--untracked-files=no'],text=True).strip())
 models=screen.get('active_models',screen['models'])
 increment_manifest=load(increment_root/'manifest.json') if (increment_root/'manifest.json').exists() else {}
 increment_models=increment_manifest.get('models',models)
 # Original evidence remains DeepSeek+Tencent; screening adds replacement vendor when used.
 vendors={'deepseek-v4.1-flash-1017':'DeepSeek','hy4-preview':'Tencent','glm-5-2-260617':'Zhipu'}
 def vendor(x):
  if x.startswith('deepseek'):return 'DeepSeek'
  if x.startswith('hy'):return 'Tencent'
  if x.startswith('mimo'):return 'Xiaomi'
  if x.startswith('minimax'):return 'MiniMax'
  return vendors.get(x,x)
 actual_annotation_vendors=sorted({'DeepSeek','Tencent'}|{vendor(x) for x in models})
 blocked_judge_vendors=sorted(set(actual_annotation_vendors)|{'ByteDance'})
 judge={'old_pool_including_screening_annotation_vendors':actual_annotation_vendors,'answer_vendor':'ByteDance',
  'old_pool_excluded_judge_vendors':blocked_judge_vendors,
  'increment_annotation_vendors':sorted({vendor(x) for x in increment_models}),'increment_models':increment_models,
  'old_pool_qualified_available_judges':[],'qualified_backup_count':0,'required_backups':1,'backup_gap':1,
  'main_judge_missing':True,'note':'Ark GLM-5.2 becomes annotator/filter and cannot judge these data. Tencent HY4 remains vendor-independent for new DeepSeek+Zhipu increment but its current HTTP402 means unavailable. Other independent vendors require successful strict preflight and human calibration; no gate relaxed.'}
 reserve=load(Path('.local/phase1/round3/pool-refresh-v3-v3/reserve-summary.json'))
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
 qualifications=[load(p) for p in sorted(Path('.local/phase1/round3/tokenhub-pool-qualification').glob('*/report.json')) if p.parent.name!='deepseek-v4.1-flash-1017']
 repaired_qualifications=[load(p) for p in sorted(Path('.local/phase1/round3/tokenhub-pool-qualification-throttled-v1').glob('*/report.json'))]
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
  'changes':['PAL-Set optional after phase2, excluded from phase1 gold and recall','long-term/short-term design: phase1 long-term only','quota-based annotator replacement now automatic; whole affected side relabeled'],
  'remaining_internal_conflicts':['role-table says two backups but explicit judge selection says one; execute one','role-table still lists old DeepSeek/MiMo; actual replacements explicitly authorized','native22/old711 references remain historical; use verified owner returns/current registry']},
  'production_projection':projection,'validation':validation,'screen':screen,'ecd':ecd,'increment':final or {'complete':False,'batches':batches,'new_points_adopted':0},'judge':judge,
  'new_replacement_qualification':qualifications,'ordinary429_repaired_qualification':repaired_qualifications,
  'calls':{'qualification_attempts':sum(x['calls'] for x in qualifications)+sum(x['new_post_attempts'] for x in repaired_qualifications),'post_attempts':sum(r['attempts'] for r in usage),'reported_tokens':sum((r['usage'] or {}).get('total_tokens',0) for r in usage),'by_model':dict(Counter(r['model'] for r in usage))},
  'private_evidence_hashes':{str(p):sha(p) for p in sorted(ROOT.glob('**/*.json')) if p.name in ('manifest.json','report.json','ledger.json')},
  'phase1_accepted':False,'owner_adoption_decision_pending':True,
  'unfinished':['owner decision on old-pool temporal screening','new incremental independent72 owner audit pending' if final else 'incremental annotation/export incomplete','judge main/backup/calibration gaps','full negative dialogue count/proportion confirmation','ECD system false-extraction evaluation not run; intake only']}
 (OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
 estimate=screen['audit_precision'];lo,hi=estimate['ci95'];text=[
 '# agent-memory 阶段1：长期记忆筛选与补量交接',
 f"生成时间：{report['generated_at']}；代码：{code}；存在已跟踪未提交改动：{dirty}。阶段1仍未验收，不进入阶段2。",
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
   f"原池时效性剔除 {screen['pool_temporary_removed']}；人工判错显式扣除 {screen['known_errors_explicitly_removed']}，两类取并集，不重复扣。筛后拟采纳池 {screen['pool_surviving_after_temporal_and_owner_rejection']}。与此前人工正例合并的拟议规模 {screen['proposed_pool_union_previous_human']}。当前实际整池采纳仍为 {screen['actual_adopted_model_pool']}；等负责人看数据决定。",
   '人工确认登记不由模型误剔除自动改写；模型筛选池与人工登记分别保存。没有自行设置筛选通过线。']
 text += ['## 增量批次',f"补量预算（条件估算，非实际产出）：以历史共同保留率和本轮时效性幸存率相乘约{100*survival:.2f}%估算，需{target}个新共同保留候选（不依赖旧池待批采纳），预计{projected_candidates}个候选、{projected_dialogues}段对话、双模型约{projection['post_call_estimate_both_models']}次POST；更换模型/整百对话批次舍入会增加实际调用。抽样前可用对话{reserve['available_field_valid_unique']}段。",'固定新种子；只用未用过且字段完整的BOTH/train，沿用原候选生成逻辑，原生标签字段不提供给模型。继承原会话切分。新增池在负责人独立72盲审前不计入可靠规模。',
 '|批次|完整对话分母|候选|共同保留|时效性剔除（任一侧临时）|引用无效（任一侧）|','|---|---:|---:|---:|---:|---:|']
 text += [f"|{r['batch']}|{r['conversations']}|{r['candidates']}|{r['joint_keep']}|{r['temporal_removed']}|{r['citation_invalid']}|" for r in batches]
 if final:text += [f"新增共 {final['conversations']} 段/{final['candidates']}候选，共同保留 {final['joint_keep']}。独立审核表 {final['audit']['sample']}条，新种子{final['audit']['seed']}，历史审核条目重叠 {final['audit']['previous_review_overlap']}。新增实际采纳 {final['new_points_adopted']}，等待负责人审核≤3错。"]
 else:text+=['补量未完成；未宣称达到700或1500。']
 if ecd:
  text += ['## ECD负样本小金标准',f"标注方式：**{ecd['annotation_method']}**，不是人工独立标注；Agent未改任何人工标签。全表{ecd['conversations']}段：无应记内容{ecd['counts']['negative']}段（{100*ecd['negative_fraction_all_conversations']:.2f}%，分母{ecd['negative_fraction_denominator']}）；有应记内容{ecd['counts']['positive']}段；不确定{ecd['counts']['uncertain']}段单列，不计正负。",'冻结非人工字段逐项核对一致，旧120表未覆盖。108段作为已确认负样本小金标准；7段正会话不自动折算为7个DuLeMon记忆点。不代表ECD总体分布，尚未用系统运行误抽评测。原文、审核理由与应记内容仅服务器.local/，对外只方法、哈希、指标。',f"回填SHA256：`{ecd['submitted_sha256']}`。"]
 text += ['## 裁判池影响',json.dumps(judge,ensure_ascii=False,indent=2),'渠道不是厂商；不能沿用已经参与标注/过滤的GLM作为裁判。主裁判和备用仍有缺口，未放宽预检，人工校准也未完成。',
 '## 用量与证据',f"完整门禁：pytest {validation['pytest_passed']}通过/{validation['pytest_seconds']}秒，ruff通过={validation['ruff_passed']}，strict mypy {validation['strict_mypy_source_files']}源文件，foundation零泄漏门通过={validation['foundation_passed']}。原始日志见validation.log。",f"当前台账POST尝试 {report['calls']['post_attempts']}；成功响应报告token {report['calls']['reported_tokens']}。失败响应无usage不按0实际用量推断。额外替代资格预检台账在tokenhub-pool-qualification目录，单独记录，未混为筛选调用。",
 f"腾讯替代候选资格检查额外调用 {report['calls']['qualification_attempts']} 次（含普通429有限重试）。原结果 {json.dumps(qualifications,ensure_ascii=False)}；限流补齐结果 {json.dumps(repaired_qualifications,ensure_ascii=False)}。旧报告不覆盖，Ark GLM历史预检复用不计本轮新调用。",
 '原始CSV、来源、请求响应、映射、调用台账只在服务器.local/，公开仓库仅方法、哈希、指标。CSV SHA256：`'+sha(Path('.local/dulemon72-v3-final-20261022.csv'))+'`。',
 '重放汇总：`uv run python scripts/report-temporal-phase1.py`；真实筛选：`with-llm uv run python scripts/continue-temporal-screen.py`；补量：`with-llm uv run python scripts/run-temporal-increment.py`。运行过的完整结果使用缓存，不重复计费。',
 '## 未完成项',*['- '+x for x in report['unfinished']]]
 rendered='\n\n'.join(text)+'\n'
 rendered=re.sub(r'(?<=\|)\n\n(?=\|)','\n',rendered)
 (OUT/'delivery.md').write_text(rendered)
 print(json.dumps({'report':str(OUT),'phase1_accepted':False}))
if __name__=='__main__':main()
