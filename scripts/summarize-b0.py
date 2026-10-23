"""Aggregate private B0 evidence. Missing adapters/labels never become zero scores."""
import argparse,json,hashlib,re,subprocess
from collections import defaultdict,Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from agent_memory.evals.metrics import ratio,latency
from agent_memory.evals.b0 import clustered_paired


def load(path):return json.loads(Path(path).read_text())
def rows(path):
 if not path.exists():return []
 with path.open() as stream:return [json.loads(s) for s in stream if s.strip()]
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def clustered(records,name):
 values=defaultdict(list)
 for row,numerator,denominator in records:values[row['conversation_id']].append((numerator,denominator))
 return ratio([(sum(a for a,_ in pairs),sum(b for _,b in pairs)) for pairs in values.values()]).to_dict()


def main():
 parser=argparse.ArgumentParser();parser.add_argument('--input',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
 root=args.input;out=args.output
 manifest=load(root/'run-manifest.json');status=load(root/'status.json') if (root/'status.json').exists() else {'status':'running'}
 source=load('docs/baselines/b0/datasets-v1.json');catalog=load('docs/evals/metric-catalog.json')
 graded=load(root/'graded-results-private.json') if (root/'graded-results-private.json').exists() else [r for p in sorted(root.glob('table-*-private.json')) for r in load(p)]
 raw=rows(root/'results-private.jsonl');usage=rows(root/'usage.jsonl');imports=rows(root/'imports-private.jsonl')
 measures={};by_type={};repeat_ranges={};flows={};invalid={}
 grouped=defaultdict(list)
 for row in graded:grouped[(row['dataset'],row['mode'],row['system'])].append(row)
 for (dataset,mode,system),items in grouped.items():
  key='/'.join((dataset,mode,system));quality=[r for r in items if not r['flow_only']];flow=[r for r in items if r['flow_only']]
  valid=[r for r in quality if type(r.get('judge_correct')) is bool]
  invalid[key]={'answer_invalid':sum(not r['answer_valid'] for r in quality),'judge_invalid':sum(r['answer_valid'] and r.get('judge_correct') is None for r in quality),'total_quality_rows':len(quality),'valid_grade_rows':len(valid)}
  values={}
  if valid:values['E1']=clustered([(r,float(r['judge_correct']),1.0) for r in valid],'E1')
  for k in (1,3,5,10):
   for metric in ('RT1','RT2','RT3','RT4','evidence_coverage'):
    pairs=[(r,float(r['retrieval'][str(k)][metric]),1.0) for r in quality if r.get('retrieval',{}).get(str(k),{}).get(metric) is not None]
    if pairs:values[f'{metric}@{k}']=clustered(pairs,metric)
  pairs=[(r,r['RT6'],1.0) for r in quality if r.get('RT6') is not None]
  if pairs:values['RT6']=clustered(pairs,'RT6')
  measures[key]={'dataset':dataset,'data_level':source[dataset]['data_level'],'sample_conversations':len({r['conversation_id'] for r in quality}),'sample_question_ids':len({r['question_id'] for r in quality}),'rows':len(quality),'baseline':'B0 vs no-memory/full-context/naive-vector','evaluation_method':'frozen dev sample; conversation-cluster bootstrap1000; ratios over valid grading only, invalids separately; uncalibrated diagnostic, not formal','values':values,'answer_models':sorted({r['answer_model'] for r in items if r.get('answer_model')}),'judge_models':sorted({r['judge_model'] for r in items if r.get('judge_model')})}
  types=defaultdict(list)
  for r in quality:types[r['category']].append(r)
  by_type[key]={cat:clustered([(r,float(r['judge_correct']),1.0) for r in rs if type(r.get('judge_correct')) is bool],'E1') for cat,rs in types.items()}
  repeats={}
  for i in range(3):
   selected=[r for r in valid if r['repeat']==i]
   repeats[str(i)]={'valid_rows':len(selected),'E1':sum(r['judge_correct'] for r in selected)/len(selected) if selected else None}
  observed=[r['E1'] for r in repeats.values() if r['E1'] is not None]
  repeat_ranges[key]={'repeats':repeats,'min':min(observed) if observed else None,'max':max(observed) if observed else None,'completed_repeats':len(observed)}
  flow_types=defaultdict(list)
  for r in flow:flow_types[r['category']].append(r)
  flows[key]={'status':'流程验证，不作质量证据','types':{cat:clustered([(r,float(r['judge_correct']),1.0) for r in rs if type(r.get('judge_correct')) is bool],'E1') for cat,rs in flow_types.items()},'rows':len(flow)}
 comparisons={}
 for dataset,mode in sorted({(r['dataset'],r['mode']) for r in graded}):
  scope=[r for r in graded if r['dataset']==dataset and r['mode']==mode and not r['flow_only']]
  system={(r['conversation_id'],r['question_id'],r['repeat']):r['judge_correct'] for r in scope if r['system']=='system' and type(r.get('judge_correct')) is bool}
  for baseline in ('no-memory','full-context','naive-vector'):
   reference={(r['conversation_id'],r['question_id'],r['repeat']):r['judge_correct'] for r in scope if r['system']==baseline and type(r.get('judge_correct')) is bool}
   key='/'.join((dataset,mode,'system-minus-'+baseline))
   comparisons[key]=clustered_paired(reference,system) if system and system.keys()==reference.keys() else {'status':'unavailable: valid paired coverage differs; invalid outputs not replaced with wrong labels'}
 failures=[]
 for r in graded:
  if r.get('judge_correct') is False or not r.get('answer_valid'):
   reason='invalid_model_output' if not r.get('answer_valid') else ('no_usable_full_chain_memory' if r['mode']=='full' and r['system']=='system' and not r['ranked_evidence_sets'] else ('retrieval_miss' if r['system'] in ('system','naive-vector') and r.get('retrieval',{}).get('10',{}).get('RT1')==0 else ('no_history_baseline_mismatch' if r['system']=='no-memory' else 'answer_mismatch_despite_context_pending_human_calibration')))
   failures.append({'id':r['row_id'],'dataset':r['dataset'],'mode':r['mode'],'system':r['system'],'type':r['category'],'reason':reason,'private_source':str(root/'graded-results-private.json'),'flow_only':r['flow_only']})
 used={metric.split('@')[0] for table in measures.values() for metric in table['values']}
 metric_status=[]
 for entry in catalog:
  mid=entry['id'];reason='observation adapter or suitable confirmed gold unavailable; not measured'
  if mid in used:reason='sample diagnostic observations available; human calibration pending for judge-derived scores'
  elif mid in ('RT4',):reason='graded memory-item relevance not supplied; source evidence grades do not automatically grade every chunk'
  elif mid in ('RT7','RT8','RT9'):reason='ablation/sensitivity/alternative-embedding experiment not executed; no optimization in this phase'
  elif mid in ('CX1','CX2'):reason='B0 counter reports conservative UTF8 bytes; actual context-only target-model token count not measured; do not relabel bytes as tokens'
  elif mid=='E3':reason='answer token counts known, upstream tokens not yet attributed fairly per comparison group; do not substitute answer-only tokens for total tokens'
  elif mid.startswith('PF'):reason='independent cross-region load host not yet supplied; no PF measurement'
  metric_status.append({**entry,'measurement_status':reason,'value':None,'n':0,'ci95':None})
 costs={}
 for role in sorted({r['role'] for r in usage}):
  calls=[r for r in usage if r['role']==role and r.get('new_http_call',not r.get('cache_hit',False)) and not r.get('fixture_only',False)];known=[r for r in calls if r.get('usage')]
  costs[role]={'post_attempts':len(calls),'known_usage_responses':len(known),'input_tokens':sum(r['usage'].get('prompt_tokens',0) for r in known),'output_tokens':sum(r['usage'].get('completion_tokens',0) for r in known),'total_tokens':sum(r['usage'].get('total_tokens',0) for r in known),'usage_unknown':len(calls)-len(known),'latency_seconds':latency([r['seconds'] for r in calls]),'attempted_wire_json_bytes':sum(r['input_bytes'] for r in calls)}
 imported=defaultdict(list)
 for row in imports:imported[(row['dataset'],row['mode'],row['repeat'])].append(row)
 import_summary=[{'dataset':k[0],'mode':k[1],'repeat':k[2],'conversations':len(v),'source_documents':sum(r['source_documents'] for r in v),'memories':sum(r['memories'] for r in v),'active_memories':sum(r['active_memories'] for r in v),'rejected_chunks':sum(len(r['rejected']) for r in v),'extraction_jobs':sum(sum(x['outcome']!='no_job' for x in r['extraction_outcomes']) for r in v),'extraction_failure_or_fallback_jobs':sum(sum(x['outcome']!='no_job' and x['extractor_last_failure']!='NONE' for x in r['extraction_outcomes']) for r in v)} for k,v in imported.items()]
 controls=load('.local/phase2/b0/correctness-v1/correctness-observations.json')
 report={'created_beijing':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),'summary_generator_commit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'run_manifest':manifest,'execution_status':status,'phase2_accepted':False,'formal_quality_scores_allowed':False,'plan':load('docs/evals/b0-policy-v1.json'),'data':source,'measurements':measures,'by_type':by_type,'paired_comparisons':comparisons,'flow_only':flows,'invalid_results':invalid,'repeated_three_range':repeat_ranges,'failure_cases':failures[:20],'failure_count':len(failures),'failure_reason_counts':dict(Counter(r['reason'] for r in failures)),'resources':costs,'imports':import_summary,'correctness_controls':controls,'metric_coverage':metric_status,'calibration_private_csv_exists':(root/'calibration-300-private.csv').exists(),'calibration_rows':300 if (root/'calibration-300-private.csv').exists() else 0,'human_calibration_received':False,'performance_measured':False,'stage3_started':False,'remaining':['owner judge calibration if private sheet available','unmeasured metric observation adapters/required labels; no invented zeros','independent load host and PF measurements','full-context over-limit truncation and context tokenizer validation','complete phase2 review and acceptance']}
 out.mkdir(parents=True,exist_ok=True);(out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
 text=['# 阶段2 B0测量进展（非完成报告）','',f"源码B0：{manifest.get('runtime_application_file')}；运行提交 {manifest['harness_commit']}；生成器提交 {report['summary_generator_commit']}。",f"状态：{status['status']}；阶段2未验收，阶段3未开始。",'', '## 方案与数据','', '最新版方案与逐条出入见 report.json.plan；B0标签未覆盖。所有输入为冻结开发集投影，测试集未运行。756个记忆点和828个可分类会话是阶段1全局混合来源规模，不冒充开发集分母。所有原文、答案和裁判原判仅服务器私有；本报告只放聚合指标和失败ID。','', '## 指标与对比（均为校准前诊断）','', '| 数据/模式/系统 | 指标 | 值 | 分母 | 会话数 | 95% CI |','| --- | --- | --- | --- | --- | --- |']
 for key,table in measures.items():
  for mid,value in table['values'].items():text.append(f"| {key} | {mid} | {value['value']} | {value['denominator']} | {value['n']} | {value['ci95']} |")
 text+=['','## 三次重复与分题型','', '逐表三次独立调用波动、分题型及配对差异见report.json；缺少三次时不声称重复完成。三类构造题在flow_only单列“流程验证，不作质量证据”，不计入真实中文汇总；本报告也不做跨数据集混合总分。', '', '## 失败案例','',f"当前失败/无效 {len(failures)} 条，列出 {min(20,len(failures))} 个真实失败ID；不足20时不凑数。"]
 text += [f"- {r['id']}：{r['dataset']}/{r['mode']}/{r['system']}，{r['reason']}" for r in failures[:20]]
 text+=['','## 正确性小样与已知不足','', '独立非属主PostgreSQL、冻结B0公开API的程序构造控制结果见correctness_controls；不称真实用户或生产数据。LC5非法状态矩阵穷举；RL1/RL2/SC1/SC3为固定三轮控制，不能外推所有对抗输入。LC7已知逻辑删除边界实测仍保留正文版本，不能声称删除完整性通过；未优化或偷偷清理被测对象。','', '## 用量与局限','',f"模型尝试 {len(usage)} 次，各角色token、未知usage及延迟见resources；完整每次输入输出仅私有。成本未折算，不查询余额、不充值。校准表当前存在：{report['calibration_private_csv_exists']}，人工结果未收到。", '裁判技术预检不代表人工校准。无效输出单列，不默认对/错；问答绝对值不与论文GPT4o口径等同。公开基准训练污染未确认。ECD客服领域不代表一般对话；现有中文查询参考的来源/审批范围如实保留。','', '## 全指标缺口与下一步','', 'EX、LC、RT、CX、E、RL、SC、PF全部目录逐项在metric_coverage列出。没有适配器、确认标签或真实观测的指标保留null/n=0/CI=null，绝不拿0冒充通过；已有观测在measurements或correctness_controls另列。当前尚不是B0全指标完成报告。', '公网PF尚未运行，等待独立压测机；准备说明已发负责人。校准私有表导出后交负责人人工判定并暂停；未校准主备不得进入正式结果，不进入阶段3。']
 (out/'delivery.md').write_text('\n'.join(text)+'\n')
 print(json.dumps({'status':status['status'],'graded_rows':len(graded),'raw_prepared_rows':len(raw),'post_attempts':len(usage),'calibration_rows':report['calibration_rows']}))

if __name__=='__main__':main()
