"""Generate replacement handoff from frozen v3 experiment, real replies and gate logs."""
import json
import re
import shutil
import subprocess
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from agent_memory.evals.evidence_v3 import read_rows, sha

ROOT = Path('.local/phase1/round3/evidence-v3-replacement')
OUT = Path('docs/reports/phase1-round3-evidence-v3-replacement-2026-10-22')
OUT.mkdir(parents=True, exist_ok=True)
subprocess.run(['uv','run','python','scripts/run-evidence-v3-replacement.py','report'],check=True)
r=json.loads((ROOT/'result.json').read_text())
items={x['item_id']:x for x in read_rows(Path('.local/phase1/chinese-expansion-v2/dulemon/items.jsonl'))}
human={x['item_id']:x for x in read_rows(Path('.local/phase1/round3/verbatim-filter/run-final/human-confirmed-labels.jsonl'))}
protected=json.loads(Path('.local/phase1/round3/followup/protected-hashes.json').read_text())
assert all(sha(Path(p))==h for p,h in protected.items())
original=Path('.local/phase1/round3/evidence-v3/split-private.json')
assert (ROOT/'split-private.json').read_bytes()==original.read_bytes()
checks=(ROOT/'check.log').read_text()
m=re.search(r'(\d+) passed in ([\d.]+)s',checks)
assert m and 'All checks passed!' in checks and 'Success: no issues found' in checks
assert 'total=8 passed=8 failed=0 tenant_leaks=0 deleted_memory_hits=0' in checks
validation={'pytest':int(m[1]),'seconds':float(m[2]),'ruff':'pass','strict_mypy':'pass',
            'foundation':'8/8; tenant_leaks=0; deleted_memory_hits=0','log_sha256':sha(ROOT/'check.log')}
preflight_paths=[Path('.local/phase1/round3/closeout/preflight-deepseek-v4-pro-ga-260813/deepseek-v4-pro-ga-260813-summary.json'),
                 Path('.local/phase1/round3/preflight-hy4-preview/hy4-preview-summary.json')]
historical=[{'path':str(p),'sha256':sha(p),'summary':json.loads(p.read_text())} for p in preflight_paths]
assert all(x['summary']['preflight_pass'] for x in historical)
availability=[]
for p in sorted(Path('.local/phase1/round3/evidence-v3-replacement-probes').glob('*.json')):
 if not p.name.endswith('.raw.json'):
  d=json.loads(p.read_text());availability.append(d)
extra_calls=len(availability)
extra_usage=sum((x.get('usage') or {}).get('total_tokens',0) for x in availability)
comparison={}
for name in ('development','final'):
 for model in r['models']:
  p=ROOT/name/model/'checked.jsonl'
  if p.exists():
   rows=read_rows(p)
   comparison[name+':'+model]={'labels':dict(Counter(x['label'] for x in rows)),
       'model_labels_before_validation':dict(Counter(x['model_label'] for x in rows)),
       'citation_invalid':sum(not x['citation_valid'] for x in rows),
       'human_keep_rejected':sum(human[x['item_id']]['label']=='keep' and x['label']!='keep' for x in rows),
       'human_keep_rejected_by_model':sum(human[x['item_id']]['label']=='keep' and x['model_label']!='keep' for x in rows),
       'human_keep_downgraded_by_citation_check':sum(human[x['item_id']]['label']=='keep' and x['model_label']=='keep' and x['label']!='keep' for x in rows),
       'citation_failure_codes':dict(Counter(c for x in rows for c in x['citation_failures']))}
full_counts={}
for model in r['models']:
 p=ROOT/'full'/model/'labels.jsonl'
 if p.exists(): full_counts[model]=dict(Counter(x['label'] for x in read_rows(p)))
audit_path=ROOT/'fresh-audit72'/'manifest.json'
audit=json.loads(audit_path.read_text()) if audit_path.exists() else None
unchanged=['docs/evals/human-confirmed-current.json','docs/evals/chinese-query-current.json',
           'src/agent_memory/evals/metrics.py','docs/plans/2026-10-21-agent-memory-interview-plan-v2.md']
assert all(subprocess.check_output(['git','show','6bc27a4:'+p])==Path(p).read_bytes() for p in unchanged)
r.update(validation=validation,historical_preflight=historical,availability_probes=availability,
         availability_calls=extra_calls,all_actual_calls=r['actual_calls']+extra_calls,
         all_reported_tokens=r['reported_total_tokens']+extra_usage,
         actual_schema_preflight_complete=(ROOT/'PREFLIGHT_COMPLETE').exists(),
         diagnosis=comparison,full_label_counts=full_counts,new_audit=audit,
         split_identical_to_original=True,split_sha256=sha(original),
         source_modified=bool(subprocess.check_output(['git','diff','--name-only','--','src','tests','scripts','docs/evals'])),
         date_beijing=str(datetime.now(ZoneInfo('Asia/Shanghai')).date()),
         target_gap=1500-r['human_positive_points'], protected_hashes=protected,
         unchanged_hashes={p:sha(Path(p)) for p in unchanged},
         data_license_note='DuLeMon original source and owner data remain server-local; public report hashes and counts only.',
         judge_implication='This new batch has DeepSeek/Tencent annotators: exclude those plus answer vendor ByteDance. Old public HY4 judge backup is ineligible for new table; Ark GLM5.2 independent but lacks stable backup/calibration.',
         delivery='current group; no p2p',phase2_started=False)
# The same known labels have historical exposure; all aggregate results are diagnostic only.
(OUT/'report.json').write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n')
shutil.copyfile(ROOT/'check.log',OUT/'validation.log')
shutil.copyfile('docs/evals/prompts/labeling-guide-v3-evidence-v1.txt',OUT/'prompt.txt')

def formatted(s):
 if s['rate'] is None: return f"未完成（已评分{s['observed']}/{s['expected']}）"
 return f"{s['correct']}/{s['expected']} = {s['rate']:.2%}"

def table(stage):
 rows=['| 分组 | Ark DeepSeek | TokenHub HY4 | 双模型联合 |','|---|---:|---:|---:|']
 for key in sorted(r[stage]['joint']):
  a,b=(formatted(r[stage]['per_model'][model][key]) for model in r['models'])
  rows.append(f"| {key} | {a} | {b} | {formatted(r[stage]['joint'][key])} |")
 return '\n'.join(rows)

f=r['frozen']
text=[
'# agent-memory 阶段1：v3替代组合离线验证交接',
f"> 🤖 由 Codex 生成 · {r['date_beijing']} · 来源 agent-memory@{r['source_commit']} · 受跟踪源码修改 {r['source_modified']}，文件SHA见report.json。",
f"**离线状态：{'通过' if r['offline_passed'] else ('未通过' if r['status']=='failed' else '未完成')}；阶段1仍未验收，不进入阶段2。**",
'## 新模型冻结与原版本关系',
'负责人消息om_x100b62a1a369a4a8df614586d52e52c已批准更换。新组合为Ark deepseek-v4-pro-ga-260813（DeepSeek）与TokenHub hy4-preview（腾讯）。这既是渠道/版本变化，也是MiMo替换成HY4；没有把它描述为原模型原样恢复。',
'使用独立的新批次目录与执行器，原始候选、主体、source不改；旧标签、旧失败批次只留历史，不与新标签拼接。原v3提示词逐字保持，原开发/最终切分逐字继承，不重新挑题。',
f"切分种子 {f['split_seed']}，开发 {sum(f['development_counts'].values())}、最终 {sum(f['final_counts'].values())}，会话重叠 {f['conversation_overlap']}；每请求候选上限 {f['batch_size']}，两模型各自串行、两渠道并行。",
'## 预检证据及真实调用',
'复用同模型同渠道既有完整采样控制/格式预检，以下不是今天重跑的结果：',
]
for x in historical:
 s=x['summary'];text.append(f"- {s['model']}：历史总调用{s['calls']}，格式{s['format_valid']}/{s['format_n']}，连续五次一致{s['consistent_5']}，关闭思考实测{s['observed_disabled_thinking']}，通过{s['preflight_pass']}；路径与SHA在report.json。")
text += [
f"本轮另做可调用性检查 {r['availability_calls']} 次，均HTTP200；再用实际v3提示词与程序构造的明确事实测试完整证据格式，完成标志 {r['actual_schema_preflight_complete']}。它是格式/引用功能检查，不是质量效果证明。",
f"本批实际请求（含可调用性与v3格式检查） **{r['all_actual_calls']}** 次，报告的token合计 **{r['all_reported_tokens']}**，缺usage调用 {r['usage_missing_calls']}；评分台账HTTP分布 {json.dumps(r['http_counts'])}。未查询余额，未充值/开通后付费，没有靠报错循环探余额。",
'## 指标定义与阈值',
'keep组记正确项保留率，discard组记错误拦截率（最终不是keep即拦截）。联合保留要求两模型都keep且各自引用有效；表格也分别给出两模型，避免联合拦截掩盖单模型误判。未完成请求不算成功拦截，rate为null。',
'程序只检查source_id唯一且绑定本条来源、role=user、quote为连续精确子串；不推断语义、不替模型补证据、不自动改候选。模型遗漏细节或引用对但语义不支持，仍可能漏过，需独立盲审。',
f"全体已知错误参考线至少8/9，人工正确两组保留各至少60%；执行器同时在开发和最终各应用同一比例，采用较保守的取整门，未在看到结果后改变。开发通过 {r['development']['passed']}，最终通过 {r['final']['passed']}，汇总通过 {r['offline_passed']}。",
'## 开发集结果',table('development'),
'## 最终集结果',table('final'),
'## 全体诊断汇总',
'| 分组 | 联合结果 |','|---|---:|',
]
for key,s in r['all_229_joint'].items():text.append(f'| {key} | {formatted(s)} |')
text += [
'此前这些人工题已用于审核/错误分析；本次最终集仅对新提示词开发隔离，不宣称历史全新盲测。本轮只锁定一个提示词版本，最终集不反复调试；不得将这批开发/最终题作为后续人工验收样本。',
'## 引用校验诊断',
'下列为全部已完成评分行的计数，不代表人工错误类型：',
'| 阶段/模型 | 引用无效条目 | 失败码计数（可重叠） |',
'|---|---:|---|',
]
for name,d in comparison.items():
 text.append(f"| {name} | {d['citation_invalid']} | {json.dumps(d['citation_failure_codes'])} |")
text += [
'缺主体/关系证据数组属于响应未满足keep证据契约，不等于原对话没有这个事实；not-user-source表示模型引用了非用户发言。不能把这些程序拦截与模型语义判断混为一谈。原始模型标签分布与程序最终标签分布分别留在report.json。',
'### 人工正确项的损失来源',
'| 阶段/模型 | 人工keep最终未保留 | 模型本身判非keep | 模型判keep但引用校验降级 |',
'|---|---:|---:|---:|',
]
for name,d in comparison.items():
 text.append(f"| {name} | {d['human_keep_rejected']} | {d['human_keep_rejected_by_model']} | {d['human_keep_downgraded_by_citation_check']} |")
text += [
'本次失败包含模型保守判定与响应证据契约执行不足两部分。不能为了提高保留率绕开引用验证，也不能把模型未提供证据等同于人工标错。开发集允许用来改进提示词，但最终集已经运行过；下一版本应保留本次结果历史并使用新的独立最终验证方案，不反复用本次最终题调到过关。',
'## 结果解释与后续',
]
if r['offline_passed']:
 text.append('离线执行门已通过，获批整批步骤可继续；离线通过并不等于金标准池已通过人工验收。')
else:
 text.append('离线执行门未通过，不启动整批重标、不生成新盲审、不增量补量，也不放宽阈值。具体效果失败或执行未完成依上面的status和分母区分。下一步先分析失败分组及引用/语义原因；若需新提示词版本，只能用开发部分修改，最终部分已消耗，不得反复用于调到过关。需提出新的独立验证方案交负责人确认。')
text += [
'### 失败原因与下一步提案（未执行）',
'已知错误中仍有一条包含来源未提到的具体位置细节，两个模型都keep且给出了可精确匹配的用户引用。这说明“引用真实”不足以证明“所有细节都支持”：模型仍可能遗漏待证明的候选细节。此最终集漏例只用于本轮报告，不转成下轮开发示例。',
'另一方面，正确项损失包含模型自己判missing/uncertain/temporary/attribution，以及模型虽keep却缺主体/核心关系证据、引用非user等格式执行问题。计数见上表；不能把格式缺失当作人工错误，也不能直接绕开校验以抬高保留率。',
'建议下一步：仅利用原开发集排查和修订提示词，使用完全虚构的结构示例说明主体/关系可共享同一段充分的用户原话、应填哪些字段，以及逐细节枚举不得遗漏；不改候选、不改校验标准、不使用本次最终结果调参。',
'新提示词若要再次取得通过证据，需要另有独立人工已核对验证集。可提议从现有未审DuLeMon候选盲抽建立新验证集（不增量抽新对话、不先整池重标），规模与方案需负责人确认。本轮未生成这张新表，不借用或催办ECD/困难集暂缓审核。现有最终切分成绩只留本版本历史，不重复调到过关。',
]
text.append(f"完整重标完成：{r['full_relabel_complete']}；新独立审核表已生成：{r['new_audit_generated']}。")
if audit:
 text.append(f"新表独立种子{audit['seed']}；未审共同keep池{audit['eligible_unreviewed_pool']}，样本{audit['sample']}，与全部既往人工核对项重叠{audit['previous_review_overlap']}，覆盖会话{audit['conversations']}；允许错误最多{audit['maximum_errors']}。原八列、source原JSON、人工两栏空白、顺序乱序且item_id不透明。只有负责人审核通过后才能增量。")
text += [
f"实际人工确认正例仍 **{r['human_positive_points']}**，距保底700缺 **{r['gap_to_minimum']}**，距目标1500缺 **{r['target_gap']}**。模型保留数不当作已验收真实规模。",
'## 裁判与未完成项',
'此新批标注厂商为DeepSeek/腾讯，且答题厂商字节，故三者不能裁判该新表；旧公开表的HY4备选不再适用于新表。Ark GLM5.2厂商独立，但新表合格稳定备选和人工校准仍有缺口，未在本轮另行更换裁判凑数。旧表数据/裁判池与新批次版本分开。',
'未完成：新的人工池验收、增量补量、真实中文保底规模、完整会话负样本闸门、新表裁判备选与人工校准；未通过/未完成的离线或整批步骤也保留为未完成。ECD与困难集人工审核保持暂缓，不催办。查询文件、人工子集、指标公式未改。',
'## 验证与证据',
f"完整检查 **{validation['pytest']} passed / {validation['seconds']}s**；ruff、strict mypy通过，foundation {validation['foundation']}。增加跨渠道独立凭据路由、完成缓存不重复调用、未过离线门禁止整批入口等测试。",
'原始请求/响应、逐条引用及人工结果留服务器.local；公开Git仅报告、方法、脚本、提示词、计数与哈希。所有报告与附件只发当前群，不私发。',
'```bash\nwith-llm uv run python scripts/run-evidence-v3-replacement.py offline\nuv run python scripts/run-evidence-v3-replacement.py report\n# 仅offline_passed=true才能执行：\nwith-llm uv run python scripts/run-evidence-v3-replacement.py full\nbash scripts/check.sh\nuv run python scripts/report-evidence-v3-replacement.py\n```',
]
body='\n\n'.join(text)+'\n';body=re.sub(r'(\|[^\n]*\|)\n\n(?=\|)',r'\1\n',body)
(OUT/'delivery.md').write_text(body)
shutil.copyfile(OUT/'delivery.md',ROOT/'agent-memory阶段1v3替代模型离线验证交接-2026-10-22.md')
print(json.dumps({'status':r['status'],'passed':r['offline_passed'],'full':r['full_relabel_complete'],'calls':r['all_actual_calls']}))
