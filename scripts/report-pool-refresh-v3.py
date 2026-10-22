"""Public metadata handoff from actual pool progress; never calls a model."""
import json
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from agent_memory.evals.evidence_v3 import sha

ROOT=Path('.local/phase1/round3/pool-refresh-v3-v3')
OUT=Path('docs/reports/phase1-round3-pool-refresh-v3-2026-10-22')
OUT.mkdir(parents=True,exist_ok=True)
subprocess.run(['uv','run','python','scripts/summarize-pool-refresh-v3.py'],check=True)
r=json.loads((ROOT/'progress-and-planning.json').read_text())
f=json.loads((ROOT/'manifest.json').read_text())
log=(ROOT/'check.log').read_text()
m=re.search(r'(\d+) passed in ([\d.]+)s',log)
assert m and 'All checks passed!' in log and 'Success: no issues found' in log
assert 'total=8 passed=8 failed=0 tenant_leaks=0 deleted_memory_hits=0' in log
validation={'pytest':int(m[1]),'seconds':float(m[2]),'ruff':'pass','strict_mypy':'pass',
 'foundation':'8/8; tenant_leaks=0; deleted_memory_hits=0','log_sha256':sha(ROOT/'check.log')}
protected=json.loads(Path('.local/phase1/round3/followup/protected-hashes.json').read_text())
assert all(sha(Path(p))==h for p,h in protected.items())
unchanged=['docs/evals/human-confirmed-current.json','docs/evals/chinese-query-current.json',
 'src/agent_memory/evals/evidence_v3.py','src/agent_memory/evals/metrics.py',
 'docs/plans/2026-10-21-agent-memory-interview-plan-v2.md']
assert all(subprocess.check_output(['git','show','1c60082:'+p])==Path(p).read_bytes() for p in unchanged)
jp=Path('.local/phase1/round3/ark/preflight-glm-5-2-260617/glm-5-2-260617-summary.json')
j=json.loads(jp.read_text());assert j['preflight_pass']
judges={'answer_vendor':'ByteDance','annotation_vendors':['DeepSeek','Tencent'],
 'excluded_vendors':['ByteDance','DeepSeek','Tencent'],
 'technically_eligible_vendors_from_existing_evidence':['Zhipu'],
 'main_candidate':'Ark:glm-5-2-260617','evidence_sha256':sha(jp),'new_call_this_round':False,
 'qualified_stable_backups':0,'minimum_backups':1,'backup_gap':1,
 'human_calibration_complete':False,'formal_judge_pool_ready':False}
r.update(frozen=f,validation=validation,judges=judges,
 source_commit=subprocess.check_output(['git','rev-parse','--short','HEAD'],text=True).strip(),
 source_modified=bool(subprocess.check_output(['git','diff','--name-only','--','src','tests','scripts','docs/evals'])),
 date_beijing=str(datetime.now(ZoneInfo('Asia/Shanghai')).date()),
 source_hashes={str(p):sha(p) for p in [Path('scripts/refresh-evidence-pool-v3-v3.py'),
   Path('scripts/complete-pool-refresh-v3.py'),Path('scripts/inventory-dulemon-reserve.py'),
   Path('scripts/summarize-pool-refresh-v3.py'),Path('src/agent_memory/evals/pool_planning.py')]},
 protected_hashes=protected,unchanged_hashes={p:sha(Path(p)) for p in unchanged},
 unfinished=['DeepSeek remaining pool annotation','complete joint production rate',
 'independent audit72','incremental sampling','700 reliable real Chinese points',
 'whole negative dialogue gates','judge backup and calibration'])
(OUT/'report.json').write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n')
shutil.copyfile(ROOT/'check.log',OUT/'validation.log')
shutil.copyfile('docs/evals/prompts/labeling-guide-v3-evidence-v3.txt',OUT/'prompt.txt')
d=r['reserve'];lo,hi=r['joint_keep_completion_bounds'];ulo,uhi=r['unexposed_joint_completion_bounds']
text=[
'# agent-memory 阶段1：701池重标进度、补量估算与用量上限阻塞',
f"> 🤖 由 Codex 生成 · {r['date_beijing']} · 来源 agent-memory@{r['source_commit']} · 未提交源码修改 {r['source_modified']}；源文件SHA见report.json。",
'**阶段1仍未验收。新规则与格式修订已执行；HY4完成整池，DeepSeek被账户设置用量上限阻塞。双标未完成，盲审表未生成，增量未做。**',
'## 负责人决定与历史版本差异',
'正确项保留率不再是通过条件，只报告产量。接受既有已知错误拦截结果，下一质量门为新独立盲审。不做新离线验证，旧失败报告不改写。范围由全部原候选收窄为扣除人工否定项后的共同保留池。',
f"既有错误拦截 **{r['historical_quality_gate']['correct']}/{r['historical_quality_gate']['total']}**；历史正确项保留率（只报告）{r['historical_retention_report_only']['blind_correct'][0]}/{r['historical_retention_report_only']['blind_correct'][1]}、{r['historical_retention_report_only']['native_correct'][0]}/{r['historical_retention_report_only']['native_correct'][1]}。新格式不复用最终半集重测，所以没有新版本人工正确项保留率；不能把池留存率混称人工正确项保留率。",
f"历史共同keep {f['old_joint_keep']}，扣除人工否定 {f['human_rejected_in_joint']}，本次 **{f['pool']}**；池中已暴露 {f['previously_exposed_in_pool']}，重标前未审候选 {f['unexposed_before_refresh']}。全部人工/开发/最终排除集合并去重 {f['exclusions']} 项。",
'## 提示词修订、失败与返工',
'旧格式示例把relation留空，与keep必填要求冲突，属于提示词问题。只读取原开发输出，用完全虚构例把subject和relation同时填全，并允许共享同一段充分用户原话。不改候选、语义规则或精确引用校验标准。',
'| 开发诊断 | 模型keep | subject空 | relation空 |',
'|---|---:|---:|---:|',
]
for model,x in f['development_diagnosis_only'].items():
 text.append(f"| {model} | {x['model_keep']} | {x['keep_empty_subject']} | {x['keep_empty_relation']} |")
text += [
f"中间格式版本遗漏原reason枚举说明，首批校验失败；实际调用 {r['actual_calls_retired_format_attempt']} 次，台账和标签留历史。恢复原枚举后建立全池新批，没有拼接旧部分标签。本轮新增离线评价调用 {r['offline_evaluation_new_calls']}；最终半集只取身份作排除，不取原始回答调提示词。",
'701池与历史已用集合存在交集：按获批范围整池重标会再次包含这些候选，但不以其人工答案计算新离线效果，且从新盲审全部排除。旧最终半集的原始评测响应不用于修订提示词。',
'## 当前真实标注进度',
'组合不变：Ark deepseek-v4-pro-ga-260813与TokenHub hy4-preview。',
'| 模型 | 完成/总数 | keep | uncertain | discard | 完整池留存率 |',
'|---|---:|---:|---:|---:|---:|',
]
for model,x in r['models'].items():
 rate=f"{x['keep_rate']:.2%}" if x['keep_rate'] is not None else '未验证（部分完成）'
 text.append(f"| {model} | {x['completed']}/{x['total']} | {x['labels'].get('keep',0)} | {x['labels'].get('uncertain',0)} | {x['labels'].get('discard',0)} | {rate} |")
text += [
'**DeepSeek返回HTTP429 / SetLimitExceeded：账户设置的安全用量上限触发，模型服务已暂停。不是普通限流，不能靠重试解决。** 两个并发流分别收到该错误后停止，无重试、替换、修改上限、充值或开通后付费。原始响应含账号标识，只留本地，公开仅错误码和哈希。',
f"当前提示批实际请求 {r['actual_calls_current_prompt']} 次，HTTP {json.dumps(r['http_current'])}；连同退休格式尝试共 {r['actual_calls_all']} 次。已报告token：当前 {r['reported_tokens_current']}、退休尝试 {r['reported_tokens_retired']}；当前缺usage {r['missing_usage_calls_current']} 次，不认定失败请求实际零消耗。",
f"两模型都完成的候选仅 {r['completed_both_items']} 条，是排序进度样本，不外推联合留存率。全池共同幸存数目前只有完成进度界 **[{lo}, {hi}]**；排除全部历史暴露后的界 **[{ulo}, {uhi}]**。它们不是抽样置信区间，上界不是已完成双标池，不能用于抽表或宣称达标。",
'## 盲审与恢复',
f"新种子 **{r['audit_seed']}**，独立抽 **{r['required_sample']}**，最多 **{r['maximum_errors']}** 错。仅在双标完整后，从两模型keep且引用有效、未人工核对且未用作开发/最终的条目中抽；八列、原JSON来源、人工栏空白、乱序、不透明编号。不足不凑表。当前未生成。",
'正式finalizer投影真实人工标签，再核对全体排除集合；黑名单占位值不是人工结果。恢复入口保留原台账，只审同提示词/同模型剩余项，不自动探测暂停服务。',
f"DeepSeek还需最少 **{r['models']['deepseek-v4-pro-ga-260813']['remaining_min_requests']}** 次请求（批上限 {f['batch_size']}）；HY4无需重跑。当前需要负责人恢复Ark该模型可用状态，本轮未擅自调整上限或改变组合。",
'## 未用DuLeMon盘点：只读，未抽样',
f"BOTH/train原始 {d['raw_train_dialogues']}；历史标注/审核已用 {d['annotation_used_unique']}，查询已用 {d['query_used_unique']}，去重并集 {d['used_union']}。按同BOTH字段、明确Usr/Bot角色、非空候选与规范化role/text精确哈希去重后，剩 **{d['available_field_valid_unique']}** 段，含 **{d['available_native_candidate_slots']}** 原生候选槽位，均值 **{d['candidates_per_available_dialogue']:.4f}** 槽/对话。槽位不是可靠正例。",
f"继承内部切分 {json.dumps(d['inherited_split_counts'])}，未迁移切分或用于调提示词。内部dev/test不等于新增训练集。原始BOTH/dev/test另留 {d['native_dev_test_held_out']} 段；SELF模式 {d['self_schema_excluded']} 段缺本流程字段，不计可用量。",
'“未用过”指未被已知标注/审核导出或冻结中文查询选用；全库格式化解析不算实质选用。索引取全部已知版本并集后去精确对话重复，未声称语义近重复全查。仍为人设条件下的人类中文对话，非生产客服日志；许可沿用母仓库说明、压缩包未单独许可的既有记录。完整负会话和比例另确认，no-said字段不自动充负会话金标。',
'## 产量与调用量：条件估算',
f"逐条人工确认正例仍 **{r['human_confirmed_positive']}**，距保底700缺 **{r['gap_to_700']}**，距目标1500缺 **{r['gap_to_1500']}**。模型幸存不增加这个数字。若目标是逐条人工确认，仍需新增至少 {r['gap_to_700']} 个人工确认正例；若按抽检通过整池采纳，须先过盲审再另报去重池规模。",
'本次联合留存率尚不完整，不能给按其计算的可靠点估计。下表是敏感性规划：候选共同幸存率是假设，人工精度假设95%只作预算，不是质量结论/置信下界；候选槽位均值来自本次真实库存。',
'| 假设候选共同幸存率 | 需对话估算 | 双模型请求估算 | 库存够否 |',
'|---|---:|---:|---|',
]
for x in r['production_scenarios']:
 text.append(f"| {x['candidate_survival_assumption']:.0%} | {x['dialogues_estimated']} | {x['calls_both_models']} | {'够（条件估算）' if x['reserve_dialogues_sufficient'] else '不足'} |")
o=r['optimistic_calibration']
if o:
 text.append(f"与本次产量相关的乐观校准：旧池密度 {r['old_selection_density_for_calibration']:.2%} × 本次联合上界占池比例，候选密度规划 {o['candidate_survival_assumption']:.2%}，约 {o['dialogues_estimated']} 对话、{o['calls_both_models']} 次请求。它假设旧池密度可迁移、缺失DeepSeek结果都保留HY4幸存、未来精度95%；不是实测联合产量或可达性保证。")
text += [
'公式：需幸存数=ceil(缺额/精度假设)，候选数=ceil(幸存数/幸存率假设)，对话按实际候选均值向上取整，再按整对话重新预算候选；双模型请求=2×ceil(候选预算/批上限)。新组合直接审核新原生候选，不再调用原DeepSeek/MiMo旧组合；原生字段枚举候选无LLM调用。未含改写、重试、裁判评测和额外人工工作，不声称实际新增。',
'## 该表裁判厂商与缺口',
f"答题字节、标注DeepSeek/腾讯须排除。已有证据中技术预检及实际成功调用符合条件的厂商清单：**{', '.join(judges['technically_eligible_vendors_from_existing_evidence'])}**；对应 {judges['main_candidate']}。引用既有完整预检与成功调用，本轮未探测裁判额度，不保证今天余额充足。",
f"技术主候选1，合格稳定备选 {judges['qualified_stable_backups']}，最低要求 {judges['minimum_backups']}，缺 **{judges['backup_gap']}**。HY4是本表标注模型，不可裁判本表；预下线GLM-5V不算稳定备选；MiMo当前不可调用，其余失败候选不放宽门槛凑数。裁判人工校准仍未完成，**正式裁判池未验收**，不把厂商独立/技术合格当成全部验收通过。",
'## 验证与未完成项',
f"完整检查 **{validation['pytest']} passed / {validation['seconds']}s**；ruff、strict mypy通过；foundation {validation['foundation']}。测试覆盖字段/去重、条件规划取整、原八列盲化排除、完整双标前禁止抽表。候选、原始来源、引用校验器、人工子集、查询与指标散列不变。",
'未完成：DeepSeek剩余标注、联合产量、新独立盲审、增量补量、真实中文保底规模、完整负会话闸门、裁判备选与人工校准。ECD和困难集表保持原样，不催办。',
'原始数据、逐条标签与服务响应只留服务器.local；公开Git仅方法/脚本/提示词/计数/哈希。报告及后续审核表只发当前群，不私发。',
'恢复命令（仅在负责人恢复同模型可用状态后）：with-llm uv run python scripts/complete-pool-refresh-v3.py recover --provider-restored。完整后才可执行finalize。该命令不修改服务限额；默认不自动探测暂停服务。',
]
body='\n\n'.join(text)+'\n';body=re.sub(r'(\|[^\n]*\|)\n\n(?=\|)',r'\1\n',body)
(OUT/'delivery.md').write_text(body)
shutil.copyfile(OUT/'delivery.md',ROOT/'agent-memory阶段1池重标进度与补量估算-2026-10-22.md')
print(json.dumps({'status':r['status'],'audit_generated':r['audit_generated'],'tests':validation['pytest']}))
