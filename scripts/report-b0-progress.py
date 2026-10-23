"""Publish aggregate B0 progress only; private QA, source text and credentials stay private."""
import argparse,collections,hashlib,json,re,subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT=Path('.local/phase2/b0')
def read(path,default=None):return json.loads(path.read_text()) if path.exists() else default
def rows(path):
 if not path.exists():return []
 with path.open() as f:return [json.loads(s) for s in f if s.strip()]
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def inspect(name):
 root=ROOT/name;status=read(root/'status.json',{'status':'running or interrupted; inspect process separately'})
 ledger=rows(root/'usage.jsonl');special=read(root/'summary.json',{})
 if not ledger and name=='runtime-pilot-v1':ledger=special.get('records',[])
 groups={}
 for role in sorted({r['role'] for r in ledger}):
  records=[r for r in ledger if r['role']==role];wire=[r for r in records if not r.get('cache_hit') and not r.get('fixture_only') and r.get('new_http_call') is not False];known=[r for r in wire if r.get('usage')]
  groups[role]={'http_attempt_records':len(wire),'cache_replays':sum(bool(r.get('cache_hit')) for r in records),'usage_reported':len(known),'usage_unknown':len(wire)-len(known),'reported_tokens':sum(r['usage'].get('total_tokens',0) for r in known),'http':dict(collections.Counter(str(r.get('http')) for r in wire)),'models':sorted({r.get('model',r.get('requested_model','unreported')) for r in records}),'response_models':sorted({r['response_model'] for r in records if r.get('response_model')})}
 raw=rows(root/'results-private.jsonl');graded=read(root/'graded-results-private.json',[])
 if not graded:graded=[r for f in root.glob('table-*-private.json') for r in read(f,[])]
 requests=list((root/'calls').glob('*-request-private.json'));request_ids={int(p.name.split('-')[0]) for p in requests};observed={r['call_id'] for r in ledger if 'call_id' in r}
 return {'name':name,'status':status,'ledger_sha256':sha(root/'usage.jsonl') if (root/'usage.jsonl').exists() else None,'prepared_context_rows':len(raw),'completed_answer_and_grade_rows':len(graded),'usage_by_role':groups,'request_ids_without_usage_record':len(request_ids-observed),'record_count_including_replays':len(ledger),'snapshot':read(root/'database-snapshot-manifest.json'),'quota_pause':{k:v for k,v in (read(root/'runtime-quota-pause.json',{}) or {}).items() if k in ('at','role','provider','model','http','error_code')},'run_manifest_sha256':sha(root/'run-manifest.json') if (root/'run-manifest.json').exists() else None,'harness_commit':read(root/'run-manifest.json',{}).get('harness_commit'),'calibration_exported':(root/'calibration-300-private.csv').exists()}
def main():
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--active',default='api-pilot-lite-v1');a=p.parse_args()
 names=['runtime-pilot-v1','api-pilot-v1','api-pilot-v2','development-sample-v1','development-sample-v3','api-pilot-lite-v1','development-sample-v4','development-sample-v5']
 runs=[inspect(name) for name in names if (ROOT/name).exists()]
 check=ROOT/'check-checkpoint.log';log=check.read_text();match=re.search(r'(\d+) passed in ([\d.]+)s',log);assert match
 commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip();baseline=subprocess.check_output(['git','rev-parse','B0^{}'],text=True).strip()
 plan=Path('docs/plans/2026-10-22-agent-memory-interview-plan-v3.md');policy=read(Path(read(Path('docs/evals/b0-current.json')).get('policy','docs/evals/b0-policy-v4.json')))
 tokenizer=read(ROOT/'context-tokens-snapshot-v1/report-private.json',{})
 tokenizer={k:v for k,v in tokenizer.items() if k not in ('records','dataset_snapshot_sha256')}
 tokenizer['historical_source_log_sha256_at_end_not_snapshot']=read(ROOT/'context-tokens-snapshot-v1/report-private.json',{}).get('dataset_snapshot_sha256')
 tokenizer['provenance_limitation']='historical sidecar hashed a growing source log at end; this is not the selected-row snapshot hash. Individual private rendered_sha256 and requests remain available. Do not treat as final B0 CX scores.'
 report={'generated_beijing':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),'generator_commit':commit,'uncommitted_changes':bool(subprocess.check_output(['git','status','--porcelain'],text=True).strip()),'baseline_tag':'B0','baseline_commit':baseline,'plan_path':str(plan),'plan_sha256':sha(plan),'policy':policy,'phase2_complete':False,'phase2_accepted':False,'formal_quality_scores_allowed':False,'active_run':a.active,'runs':runs,'checks':{'pytest_passed':int(match[1]),'pytest_seconds':float(match[2]),'ruff_passed':'All checks passed!' in log,'strict_mypy_passed':'Success: no issues found' in log,'foundation_passed':'total=8 passed=8 failed=0' in log,'log_sha256':sha(check),'source_scope':'measurement harness source before current report generation; source file hashes below','measured_source_sha256':{str(p):sha(p) for p in [Path('scripts/run-b0.py'),Path('src/agent_memory/evals/b0.py'),Path('tests/integration/test_b0_harness.py')]}},'phase1_accepted_counts':{'reliable':read(Path('docs/evals/reliable-chinese-current.json')),'negative':read(Path('docs/evals/negative-conversations-current.json'))},'frozen_data':read(Path('docs/baselines/b0/datasets-v1.json')),'correctness_fixture_observations':read(Path('docs/baselines/b0/correctness-observations-v2.json')),'historical_context_tokenizer_diagnostic':tokenizer,'remaining':['all requested metrics and missing observation adapters; undefined values remain null','complete new-model sampled answers and grading, repeats and >=20 categorized failure cases','private 300-row calibration export and owner labels; backup judge calibration also pending','judge-derived metrics cannot become formal before calibration','independent cross-region load host and PF1-PF10; preparation delivered to group','full-context real over-limit branch not yet exercised; offline branch regression is not live evidence','phase2 owner acceptance; no automatic phase3'],'test_set_executed':False,'phase3_started':False}
 catalog=read(Path('docs/evals/metric-catalog.json'));report['metric_coverage']=[{**r,'value':None,'sample_size':None,'ci95':None,'status':'pending formal complete measurement; limited fixture observations separately disclosed'} for r in catalog]
 a.output.mkdir(parents=True,exist_ok=True);(a.output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
 text=['# agent-memory 阶段2 B0执行交接（进行中，非验收报告）','',f"生成：{report['generated_beijing']}；工具源码：{commit}；B0：{baseline}。报告生成时是否存在未提交修改：{report['uncommitted_changes']}。业务源码标签未覆盖。",'', '## 当前状态','',f"当前轮：{a.active}。阶段2尚未完成，正式质量分数尚未获准，未进入阶段3。旧pro因429/SetLimitExceeded暂停；更换DeepSeek后的新轮因402暂停。负责人明确授权换型后，Ark lite按原标准复验通过，正在新的独立目录运行。失败仅代表相应型号/身份的实际失败，不是所有模型余额结论。",'', '## 方案与数据口径','',f"完整重读：{plan}，SHA256 `{sha(plan)}`。与前轮同文件；本轮负责人约定与文件的出入："]
 text+=['- '+x for x in policy['plan_differences']]
 text+=['',f"数据：冻结全局{report['phase1_accepted_counts']['reliable']['accepted_union']}记忆点、{report['phase1_accepted_counts']['negative']['denominator']}个可分类会话，非全部来自DuLeMon；ECD确认负会话{report['phase1_accepted_counts']['negative']['numerator']}。开发集投影及输入哈希见report.json.frozen_data，不能用全局数冒充开发集分母。ECD为客服领域，不代表一般对话；AI草稿加人工确认，不称独立人工标注。所有原文、问题、答案、私有校准及响应仅服务器。测试集未执行。",'', '## 已执行记录（上下文不等于答题成绩）','', '| 轮次 | 状态 | 准备上下文行 | 完成答题和判分行 | HTTP尝试 | 向量重放 |','| --- | --- | ---: | ---: | ---: | ---: |']
 for r in runs:
  text.append(f"| {r['name']} | {r['status']['status']} | {r['prepared_context_rows']} | {r['completed_answer_and_grade_rows']} | {sum(x['http_attempt_records'] for x in r['usage_by_role'].values())} | {sum(x['cache_replays'] for x in r['usage_by_role'].values())} |")
 text+=['','每轮角色、型号、HTTP、已报告token、未知usage与未配对请求见JSON；关机status可能早于晚到usage，最终以完整台账核算。价格和余额未验证，不以未知usage当0。旧操作小样有基线实现问题，不能用于正式对比；旧上下文预算显式100000，不是B0默认2000。','', '## 框架纠错与对比边界','', '朴素向量直写库覆盖全部原文分块，包括被系统策略拒绝的块；余弦一个通道，无过滤、词法或融合。系统派生向量走冻结embedding worker。真实向量的校验重放有单独台账，历史token不算新消耗，零重放延迟不冒充系统性能或缓存收益。旧抽取输出不拼接到新型号。系统candidate不偷偷激活。全文超限截断只在明确超限错误时执行，从最旧端截断并记录序列化字符比例；真实超限分支尚未验证。','', '## 指标、重复与失败案例','', '完整目录的未测值、样本量及CI均保留null，见metric_coverage；没有观测不写成0分或通过。当前尚无完整新模型质量对比、分题型最差项、三次关键结论波动及20个正式失败案例，不把未校准试跑凑成最终报告。三类程序构造题只作流程验证，与真实中文分开。历史真实tokenizer诊断有60次请求，其原日志末尾哈希不是选中快照哈希，限制已单列。','', '程序构造正确性控制（完整观测见JSON，不能外推一般对话质量）：LC5穷举非法转换均拒绝；RL1/RL2并发控制没有重复/丢失更新；SC1已知ID跨租户、SC3空权限控制没有成功越权。均仅有限夹具。LC7三轮逻辑删除仍各有2个正文版本，不能声称删除完整性通过；向量、事件、备份尚未全查。未优化系统或物理清理。','', '## 校准与压测','', '主裁判与备选只有技术预检，尚未人工校准。尚未交付完整300条人工空栏盲校准表，κ、准确率、假阳性与100条三次稳定性均未验证。独立压测机准备说明已发本群；在负责人提供机器前不执行公网PF。两端指纹、带宽、RTT、发压端70%无效判据、客户端/服务端耗时分开等均待实测，不能声称压测机可释放。','', '## 测试与剩余工作','',f"框架检查：pytest {int(match[1])} passed in {float(match[2])}s；ruff、strict mypy、foundation结果见JSON。检查对象为测量工具当前版本，不是把当前业务代码当B0；原B0另有冻结源码测试记录。"]
 text+=['- '+x for x in report['remaining']]
 (a.output/'delivery.md').write_text('\n'.join(text)+'\n');print(json.dumps({'report':str(a.output),'active':a.active,'runs':len(runs),'phase2_complete':False}))

if __name__=='__main__':main()
