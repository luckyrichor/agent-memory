"""Generate full replacement/audit handoff; private reviewer data never enters Git."""
import csv,json,math,re,shutil,subprocess
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from agent_memory.evals.evidence_v3 import read_rows,sha
from agent_memory.evals.pool_planning import production_scenario
from agent_memory.evals.approved_audit import FIELDS
from agent_memory.evals.human_review import digest

ROOT=Path('.local/phase1/round3/tokenhub-pool-v4/deepseek-v4.1-flash-1017')
OUT=Path('docs/reports/phase1-round3-tokenhub-pool-2026-10-22')
OUT.mkdir(parents=True,exist_ok=True)
manifest=json.loads((ROOT/'manifest.json').read_text())
for p,h in manifest['files'].items():assert sha(Path(p))==h
y=json.loads((ROOT/'yield-summary.json').read_text())
audit=json.loads((ROOT/'audit72/manifest.json').read_text())
left=read_rows(ROOT/'replacement-complete-checked.jsonl')
right=read_rows(ROOT/'hy4-complete-checked.jsonl')
items={r['item_id']:r for r in read_rows(ROOT/'pool-items.jsonl')}
allitems={r['item_id']:r for r in read_rows(Path('.local/phase1/chinese-expansion-v2/dulemon/items.jsonl'))}
human=read_rows(Path('.local/phase1/round3/verbatim-filter/run-final/human-confirmed-labels.jsonl'))
exposed={r['item_id'] for r in human}
split=json.loads(Path('.local/phase1/round3/evidence-v3-replacement/split-private.json').read_text())
exposed|=set(split['development'])|set(split['final'])
mapping=json.loads((ROOT/'audit72/opaque-map-private.json').read_text())
assert not set(mapping.values())&exposed and len(mapping)==audit['sample']
key=lambda r:json.dumps({k:r[k] for k in ('candidate','subject','source')},sort_keys=True,ensure_ascii=False)
old_contents={key(allitems[k]) for k in exposed}
assert all(key(items[k]) not in old_contents for k in mapping.values())
blind=read_rows(ROOT/'audit72/audit-blind.jsonl')
with (ROOT/'audit72/audit-blind.csv').open(encoding='utf-8-sig',newline='') as stream:
 reader=csv.DictReader(stream);assert tuple(reader.fieldnames)==FIELDS;csvrows=list(reader)
assert len(csvrows)==len(blind)==audit['sample']
for row,wire in zip(blind,csvrows):
 assert not wire['human_label'] and not wire['human_reason']
 assert wire['record_sha256']==digest(row) and json.loads(wire['source'])==row['source']
log=(ROOT/'check.log').read_text();m=re.search(r'(\d+) passed in ([\d.]+)s',log)
assert m and 'All checks passed!' in log and 'Success: no issues found' in log
assert 'total=8 passed=8 failed=0 tenant_leaks=0 deleted_memory_hits=0' in log
validation={'pytest':int(m[1]),'seconds':float(m[2]),'ruff':'pass','strict_mypy':'pass',
 'foundation':'8/8; tenant_leaks=0; deleted_memory_hits=0','log_sha256':sha(ROOT/'check.log')}
oldcheck=(ROOT/'check-before-import-fix.log').read_text()
checkfailure=re.search(r'(\d+) failed, (\d+) passed in ([\d.]+)s',oldcheck)
qualification=json.loads(Path('.local/phase1/round3/tokenhub-pool-qualification/deepseek-v4.1-flash-1017/report.json').read_text())
probes=[]
for p in sorted(Path('.local/phase1/round3/tokenhub-pool-fallback-probes').glob('**/*.json')):
 if p.name.endswith('-response-private.json') or p.name=='catalog-private.json':continue
 d=json.loads(p.read_text())
 if 'model' in d and 'http' in d:
  probes.append({**d,'sha256':sha(p),'file':str(p),'api_json_mode':'no-json-mode' not in str(p)})
catalog=json.loads(Path('.local/phase1/round3/tokenhub-pool-fallback-probes/catalog-private.json').read_text())
ledger=[r for p in sorted(ROOT.glob('*/*/ledger.json')) for r in json.loads(p.read_text())]
reserve=json.loads(Path('.local/phase1/round3/pool-refresh-v3-v3/reserve-summary.json').read_text())
confirmed=sum(r['label']=='keep' for r in human)
gap=max(0,700-confirmed)
# Unfiltered raw candidates differ from the already selected 701-pool.
# The old selected share is an explicitly assumed support-density calibration only.
old_pool_share=711/len(allitems)
density=old_pool_share*y['joint_retention']
plans=[]
for scale in (.5,1.,2.):
 p=production_scenario(gap=gap,candidates_per_dialogue=reserve['candidates_per_available_dialogue'],
                       candidate_survival=min(1,density*scale),precision_assumption=.95)
 p.update(kind='raw candidate density sensitivity, conditional',density_scale=scale,
          reserve_sufficient=p['dialogues_estimated']<=reserve['available_field_valid_unique'])
 plans.append(p)
conditional_adopted=confirmed+max(0,y['unexposed_survivors']-audit['maximum_errors'])
aftergap=max(0,700-conditional_adopted)
after=production_scenario(gap=aftergap,candidates_per_dialogue=reserve['candidates_per_available_dialogue'],
                          candidate_survival=density,precision_assumption=.95)
after['manual_positive_confirmations_required_for_individual_gold']=gap
after['scenario_goal']='reliable-pool deficit after conditional audit acceptance; individual confirmations remain separate'
protected=json.loads(Path('.local/phase1/round3/followup/protected-hashes.json').read_text())
assert all(sha(Path(p))==h for p,h in protected.items())
unchanged=['docs/evals/human-confirmed-current.json','docs/evals/chinese-query-current.json',
           'src/agent_memory/evals/evidence_v3.py','src/agent_memory/evals/metrics.py',
           'docs/evals/prompts/labeling-guide-v3-evidence-v3.txt']
assert all(subprocess.check_output(['git','show','b689691:'+p])==Path(p).read_bytes() for p in unchanged)
result={
 'date_beijing':str(datetime.now(ZoneInfo('Asia/Shanghai')).date()),
 'source_commit':subprocess.check_output(['git','rev-parse','--short','HEAD'],text=True).strip(),
 'source_modified':bool(subprocess.check_output(['git','diff','--name-only','--','src','tests','scripts','docs/evals'])),
 'phase1_accepted':False,'incremental_started':False,'new_offline_owner_evaluation':False,
 'manifest':manifest,'yield':y,'audit':audit,'probe_results':probes,'catalog_http':catalog['http'],
 'catalog_model_count':len(catalog['models']),'qualification':qualification,'validation':validation,
 'retired_partial_ark_labels_used':False,'hy4_full_replay':len(right),'hy4_new_calls':0,
 'current_calls':len(ledger),'preflight_calls':qualification['calls'],'probe_calls':len(probes),
 'all_new_post_calls':len(ledger)+qualification['calls']+len(probes),'catalog_get_calls':1,
 'current_reported_tokens':sum((r.get('usage') or {}).get('total_tokens',0) for r in ledger),
 'preflight_reported_tokens':qualification['reported_tokens'],
 'probe_reported_tokens':sum((r.get('usage') or {}).get('total_tokens',0) for r in probes),
 'current_http_counts':dict(Counter(str(r.get('http_status')) for r in ledger)),
 'current_returned_model_names':sorted({r.get('returned_model') for r in ledger if r.get('returned_model')}),
 'per_model':{name:{'counts':dict(Counter(r['label'] for r in rows)),
                   'citation_invalid':sum(not r['citation_valid'] for r in rows),
                   'citation_codes':dict(Counter(c for r in rows for c in r['citation_failures']))}
              for name,rows in [(manifest['changed_model'],left),('hy4-preview',right)]},
 'initial_check_failure':None if not checkfailure else {'failed':int(checkfailure[1]),'passed':int(checkfailure[2]),'seconds':float(checkfailure[3]),'reason':'missing result-assembly import; fixed without new model request'},
 'same_candidate_content_prior_overlap':0,
 'audit_prior_conversation_overlap':len({items[k]['conversation_id'] for k in mapping.values()} & {allitems[k]['conversation_id'] for k in exposed}),
 'audit_candidate_level_exclusion':True,'audit_human_completed':False,'audit_passed':None,
 'audit_csv_sha256':sha(ROOT/'audit72/audit-blind.csv'),
 'human_positive_points':confirmed,'human_positive_conversations':len({allitems[r['item_id']]['conversation_id'] for r in human if r['label']=='keep'}),
 'gap_to_700':gap,'gap_to_1500':max(0,1500-confirmed),'reserve':reserve,
 'old_selected_share_assumption':old_pool_share,'raw_density_calibrated_assumption':density,
 'production_sensitivity':plans,'conditional_after_audit_max3':{'hypothetical_reliable_points':conditional_adopted,'gap':aftergap,'plan':after,'not_adopted':True},
 'judges':{'excluded_vendors':['ByteDance','DeepSeek','Tencent'],
           'technically_eligible_vendors_from_existing_evidence':['Zhipu'],
           'main_candidate':'Ark:glm-5-2-260617','stable_backup_count':0,'backup_gap':1,
           'human_calibration_complete':False,'formal_pool_ready':False,'new_quota_probes':0},
 'historical_error_gate':{'correct':8,'n':9,'version':'prior Ark DeepSeek+TokenHub HY4; owner accepted for this workflow','not_retested_for_new_pair':True},
 'protected_hashes':protected,'unchanged_hashes':{p:sha(Path(p)) for p in unchanged},
 'official_parameter_reference':'https://cloud.tencent.com/document/product/1823/132248',
 'audit_delivery_message_id':'om_x100b62a37abe34a4ce5cc355b3f11fb',
}
(OUT/'report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
shutil.copyfile(ROOT/'check.log',OUT/'validation.log')
shutil.copyfile('docs/evals/prompts/labeling-guide-v3-evidence-v3.txt',OUT/'prompt.txt')
text=[
'# agent-memory 阶段1：腾讯替代组合完整重标与新独立盲审',
f"> 🤖 由 Codex 生成 · {result['date_beijing']} · 来源 agent-memory@{result['source_commit']} · 未提交源码修改 {result['source_modified']}；执行及数据SHA见report.json。",
'**完整双标已完成，新独立盲审表已发当前群，等待负责人回填；尚未通过人工验收，阶段1未验收，不做增量补量。**',
'## 更换授权与数据版本',
'负责人最新授权额度不足自动换模型、Ark不足优先腾讯。当前组合为TokenHub deepseek-v4.1-flash-1017（DeepSeek）与TokenHub hy4-preview（腾讯）；额度不足不再重复索要换型确认，但不修改上限/计费，不放宽校验与盲审标准。',
f"受影响模型侧对整个 {y['pool']} 条重新标注；此前Ark DeepSeek部分标签全部留历史，未混入。HY4的 {len(right)} 条完整结果因同池、同提示词、同型号/渠道且源文件SHA吻合整份复用，本轮新增HY4调用 {result['hy4_new_calls']}。这不是用旧模型部分标签接尾。",
'提示词、候选、原始JSON来源与精确引用校验器逐字不变；未新增负责人题目的离线评价，也未使用旧最终集调整提示词。',
'## 选型、接口兼容与预检',
f"从当前目录读取HTTP {catalog['http']}，模型数 {len(catalog['models'])}。最小可调用性请求 {len(probes)} 次，不查余额、不激活后付费；实际尝试及错误码均列report.json。",
'部分Flash候选返回400006，实际含义是请求的服务端response_format模式不受支持，不是没额度或模型不存在。仅省略这个可选API模式后实际可调用；程序端严格JSON、字段、用户角色、原文子串校验保持。不能把API模式兼容与降低输出标准混为一谈。',
'思考开关和温度控制参照[TokenHub官方DeepSeek调用指南](https://cloud.tencent.com/document/product/1823/132248)，具体型号可用性以本轮真实响应为准。',
f"选中型号：预检 {qualification['calls']} 次，其中连续五次一致 {qualification['consistent_5']}，格式 {qualification['format_valid']}/{qualification['format_n']}，请求temperature=0且无思考输出 {qualification['observed_disabled_thinking']}。另用完全虚构事实通过真实v3证据格式检查；这些是接口/控制资格检查，不是新增人工数据质量评价。",
'## 完整标注与实际产量',
'| 模型 | keep | uncertain | discard | 引用校验无效 |','|---|---:|---:|---:|---:|',
]
for model,d in result['per_model'].items():
 c=d['counts'];text.append(f"| {model} | {c.get('keep',0)} | {c.get('uncertain',0)} | {c.get('discard',0)} | {d['citation_invalid']} |")
text += [
f"共同keep **{y['joint_keep']}/{y['pool']} = {y['joint_retention']:.2%}**；排除已人工核对/开发/最终使用的幸存项 {y['exposed_survivors']} 后，未审幸存池 **{y['unexposed_survivors']}**。这些都是候选，不是新增可靠金标。保留率只报告，不作为通过条件。",
f"本轮新增POST请求 **{result['all_new_post_calls']}**：选型 {len(probes)}、控制/格式预检 {qualification['calls']}、v3格式检查及整侧标注 {len(ledger)}；另GET目录 {result['catalog_get_calls']} 次。标注/格式阶段HTTP分布 {json.dumps(result['current_http_counts'])}。",
f"服务报告token：选型 {result['probe_reported_tokens']}、技术预检 {result['preflight_reported_tokens']}、格式检查及整侧标注 {result['current_reported_tokens']}。失败可调用性请求无usage时不推定实际零消耗；复用HY4不重复计新消耗。",
'## 新独立盲审表',
f"固定新种子 **{audit['seed']}**，从未审池 **{audit['eligible_unreviewed_pool']}** 中简单随机不放回抽 **{audit['sample']}**，顺序打乱，覆盖 **{audit['conversations']}** 会话。八列严格为 "+', '.join(FIELDS)+'；source保持原JSON逐轮结构，人工两栏空白，item_id为不透明编号；不含模型标签、参照或行级分类提示。',
f"与全部历史审核/开发/最终条目ID重叠 **{audit['previous_review_overlap']}**，与历史候选+主体+来源完全相同内容重叠 **{result['same_candidate_content_prior_overlap']}**。排除单位是条目，不是整个会话；有 **{result['audit_prior_conversation_overlap']}** 个来源会话曾出现在历史审核/验证的其他条目中，未声称整会话未见。当前用户要求的条目级排除已满足。",
f"通过标准保持 **错误不超过 {audit['maximum_errors']}/{audit['sample']}**。负责人未回填，精度及置信区间未计算，不能用共同留存率冒充正确率。收到真实回填后再按冻结映射计分；没有自动填人工栏。CSV SHA256：{result['audit_csv_sha256']}。",
'审核表已发本群：DuLeMon独立盲审72条-v3更新-2026-10-22.csv。请填写human_label及human_reason后回传；回填前不补量。',
'## 真实规模与补量估算',
f"逐条人工确认仍 **{confirmed}** 点、**{result['human_positive_conversations']}** 会话，距保底700缺 **{gap}**，距目标1500缺 **{result['gap_to_1500']}**。模型拒绝已有人工正确项不会删除人工金标，模型保留也不自动增加人工金标。",
f"可用未选用BOTH/train对话仍 **{reserve['available_field_valid_unique']}**，原生候选槽位 **{reserve['available_native_candidate_slots']}**，均值 **{reserve['candidates_per_available_dialogue']:.4f}**；只读库存未做增量抽样，原内部切分不改。",
'新池留存率的分母是旧模型已筛选的共同keep层，不能直接把它套在所有新原生候选上。以下将旧共同保留比例作为可支持密度代理，再乘本轮实际留存；仅为条件规划，新组合直接双审新原生候选，不再调用旧不可用组合。',
f"校准代理密度：{old_pool_share:.2%} × {y['joint_retention']:.2%} = **{density:.2%}**。还假设新对话分布可迁移、未来人工精度95%（不是质量下界），并把代理密度减半/加倍做敏感性分析；不是对未来产量的保证。",
'| 密度假设 | 需对话估算 | 双模型请求估算 | 当前库存够否 |','|---|---:|---:|---|',
]
for p in plans:
 text.append(f"| {p['candidate_survival_assumption']:.2%} | {p['dialogues_estimated']} | {p['calls_both_models']} | {'够（条件）' if p['reserve_sufficient'] else '不足'} |")
text += [
f"如果新盲审通过，且按抽检通过整池采纳规则把未审池扣除最多{audit['maximum_errors']}个已知错误后计入，假设可靠规模为 {conditional_adopted}，还缺 {aftergap}；按中间密度假设约需 {after['dialogues_estimated']} 新对话、{after['calls_both_models']} 次双模型请求。**这只是通过后的预算，不是当前采纳规模。** 若目标是逐条人工确认700点，仍须新增{gap}个逐条确认，不能以池估计代替。",
'公式：需幸存数=ceil(缺额/精度假设)，再除候选密度、按每对话候选均值向上取整，按整对话重算候选预算；请求=2×ceil(候选预算/8)。不含重试、裁判评测及额外人工工作；原生候选字段枚举无模型调用。实际补量仍待盲审通过。',
'## 质量证据与裁判影响',
'旧8/9是此前组合的历史错误拦截证据，负责人已接受用于本流程；新替代模型未重复跑旧最终题，不能把该历史数冒称新模型实测。新组合当前数据质量等待新72条独立人工盲审。',
'答题厂商字节、标注厂商DeepSeek/腾讯仍须从该表裁判中排除。已有技术预检及实际调用证据符合条件的厂商为智谱，主候选Ark glm-5-2-260617；合格稳定备选0，要求至少1，缺1。HY4不能兼任该表裁判；预下线GLM-5V不计稳定备选。人工校准未完成，正式裁判池仍未验收。本轮没有再探测裁判额度或凑数。',
'## 验证与未完成项',
f"完整检查：**{validation['pytest']} passed / {validation['seconds']}s**；ruff、strict mypy通过；foundation {validation['foundation']}。测试覆盖无API JSON模式时真实请求hash一致、严格引用校验不变、完整缓存不重复调用、局部结果不得抽表，以及仅额度错误允许自动轮换。",
]
if checkfailure:
 text.append(f"返工如实记录：初次检查 {int(checkfailure[1])} failed / {int(checkfailure[2])} passed，原因是适配器结果汇总漏导入read_rows；已修复并完整重跑。虚构格式响应先前已合格，修复后从缓存完成，未重复调用；修改前代码/清单及新SHA留本地历史，提示词和校验标准未变。")
text += [
'已完成：腾讯替代模型资格预检、受影响侧完整701重标、未变侧完整复用、联合产量、独立72条表、补量预算与交接。未完成：负责人回填、池质量验收、增量补量、700保底规模、完整负会话闸门、裁判备选及人工校准。ECD/困难集人工表保持不动，不催办。',
'原始标签、逐条引用、匿名ID映射与审核内容只留服务器和本群附件，不进Git；公开仓库只方法/脚本/提示词/计数/哈希。阶段1未验收，不进入阶段2。所有交付发本群，不私发。',
]
body='\n\n'.join(text)+'\n';body=re.sub(r'(\|[^\n]*\|)\n\n(?=\|)',r'\1\n',body)
(OUT/'delivery.md').write_text(body)
shutil.copyfile(OUT/'delivery.md',ROOT/'agent-memory阶段1腾讯替代重标与独立盲审交接-2026-10-22.md')
print(json.dumps({'joint_keep':y['joint_keep'],'eligible':y['unexposed_survivors'],'audit':audit['sample'],'calls':result['all_new_post_calls'],'tests':validation['pytest']}))
