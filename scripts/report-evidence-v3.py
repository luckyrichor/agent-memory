"""Generate public metadata-only handoff; no private source text or audit IDs published."""
import json
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from agent_memory.evals.evidence_v3 import read_rows, sha

ROOT = Path('.local/phase1/round3/evidence-v3')
OUT = Path('docs/reports/phase1-round3-evidence-v3-2026-10-22')
OUT.mkdir(parents=True, exist_ok=True)
subprocess.run(['uv', 'run', 'python', 'scripts/run-evidence-v3.py', 'report'], check=True)
r = json.loads((ROOT / 'result.json').read_text())
r['source_modified'] = bool(subprocess.check_output(['git', 'diff', '--name-only', '--', 'src', 'tests', 'scripts', 'docs/evals']))
log = (ROOT / 'check.log').read_text()
m = re.search(r'(\d+) passed in ([\d.]+)s', log)
assert m and 'All checks passed!' in log and 'Success: no issues found' in log
assert 'total=8 passed=8 failed=0 tenant_leaks=0 deleted_memory_hits=0' in log
protected = json.loads(Path('.local/phase1/round3/followup/protected-hashes.json').read_text())
assert all(sha(Path(p)) == h for p,h in protected.items())
unchanged = [
    'docs/evals/human-confirmed-current.json', 'docs/evals/chinese-query-current.json',
    'docs/evals/phase1-round3-policy-v4.json', 'src/agent_memory/evals/metrics.py',
    'docs/plans/2026-10-21-agent-memory-interview-plan-v2.md',
]
assert all(subprocess.check_output(['git', 'show', '1f54744:'+p]) == Path(p).read_bytes() for p in unchanged)
errors = []
for model in r['frozen']['models']:
    p = ROOT / 'development' / model / '0000-response.json'
    if p.exists():
        d = json.loads(p.read_text()).get('error', {})
        errors.append({'model': model, 'code': d.get('code'), 'type': d.get('type'),
                       'meaning': 'free trial quota exhausted; postpaid not enabled', 'response_sha256': sha(p)})
validation = {'pytest': int(m[1]), 'seconds': float(m[2]), 'ruff': 'pass',
              'strict_mypy': 'pass', 'foundation': '8/8; tenant_leaks=0; deleted_memory_hits=0',
              'log_sha256': sha(ROOT / 'check.log')}
r.update(validation=validation, provider_errors=errors,
         date_beijing=str(datetime.now(ZoneInfo('Asia/Shanghai')).date()),
         unchanged_hashes={p:sha(Path(p)) for p in unchanged}, protected_hashes=protected,
         unfinished=['complete v3 offline model experiment', 'v3 full batch relabel if qualified',
                     'new independent audit72', 'incremental annotation after audit passes',
                     '700 real Chinese positives', 'whole negative conversation gates',
                     'synthetic judge backup and human judge calibration'],
         delivery_target='current group; no p2p',
         evidence_note='No raw owner text, raw questions, keys or opaque audit mappings in public report.')
(OUT / 'report.json').write_text(json.dumps(r, ensure_ascii=False, indent=2)+'\n')
shutil.copyfile(ROOT / 'check.log', OUT / 'validation.log')
shutil.copyfile('docs/evals/prompts/labeling-guide-v3-evidence-v1.txt', OUT / 'prompt.txt')
f = r['frozen']
text = [
'# agent-memory 阶段1：标注规程 v3 与离线验证额度阻塞交接',
f"> 🤖 由 Codex 生成 · {r['date_beijing']} · 来源 agent-memory@{r['source_commit']} · 未提交受跟踪源码修改：{r['source_modified']}；完整源文件SHA见report.json。",
'**阶段1仍未验收，不进入阶段2。v3实现已完成；模型效果离线验证未完成，不能判通过或效果不通过。整批重标、新盲审及补量均未启动。**',
'## 做了什么及与旧方案的变化',
'负责人最新授权取代上一轮未通过的字符串过滤路径：冻结模型不变，只升级提示词，要求每个具体细节附用户原话与source_id。新提示词独立版本，不覆盖旧annotation-v3/v5文件；模型原始输出及引用检查结果分开保存。',
'程序只做用户角色、来源身份和连续原文子串精确检查；不判断语义支持、细节是否穷尽。不再以字符串片段拼接/关键词规则作为保留判据。主体关系证据必填是响应结构约束，不能保证归属语义正确。',
'问句/假设/否定/第三人/助手先提不能变成本人肯定事实；一次行为不能变长期偏好；日期须绑定同一事件；这些由模型按完整上下文判断。即使引用是真的，语义仍可能错误，因此必须再做未审样本人工盲审。',
'## 开发与最终验证冻结',
f"本轮固定划分种子 **{f['split_seed']}**，按conversation_id隔离，会话重叠 **{f['conversation_overlap']}**；开发 {sum(f['development_counts'].values())} 条，最终 {sum(f['final_counts'].values())} 条。只锁定 {f['prompt_variants_allowed_this_run']} 个提示词版本，最终集最多完整评价 {f['final_evaluation_runs_allowed']} 次。人工答案只用来平衡划分/计算指标，从不进入模型输入。",
'| 来源分组 | 开发 | 最终 | 全部 |',
'|---|---:|---:|---:|',
]
for key in sorted(f['development_counts']):
 a,b=f['development_counts'][key],f['final_counts'][key]
 text.append(f'| {key} | {a} | {b} | {a+b} |')
text += [
'这些人工题此前已用于审核和错误分析，不能把新最终切分宣称为历史未暴露基准。本轮未利用最终集调提示词；也没有以模型结果选择切分。',
f"离线参考线：已知错误拦截至少 **{8}/{9}**；两组人工正确项保留分别至少 **{f['thresholds']['blind_correct_retention']:.0%}**、**{f['thresholds']['native_correct_retention']:.0%}**；旧表discard仅报告拦截率。执行器在开发/最终/汇总各核对同一比例，小样错误组向上取整，比只看汇总保守；不放宽参考线。",
'## 实际调用与阻塞',
f"冻结模型：{'、'.join(f['models'])}，渠道 {f['provider']}。实际请求 **{r['actual_calls']}** 次，HTTP计数 `{json.dumps(r['http_counts'])}`。每模型只试首个开发批次一次，无重试、无自动换模型；最终集未调用。",
'| 模型 | HTTP | 服务错误码 | 返回含义 |',
'|---|---|---|---|',
]
for e in errors:
 text.append(f"| {e['model']} | 402 | {e['code']} ({e['type']}) | 免费试用额度耗尽，未开通后付费 |")
text += [
'这是实际服务响应，不是推测余额。没有查询余额、充值或开通后付费，也没有按错误消息去修改计费配置。',
f"API没有返回usage的调用 **{r['usage_missing_calls']}** 次；已返回usage之和 {r['reported_total_tokens']} 不能当作实际零消耗或完整用量。私有原始响应和请求哈希已保留，公开报告仅列错误码和哈希。",
'## 要求的效果指标（联合保留口径）',
'| 分组 | 人工分母 | 有效评分数量 | v3结果 |',
'|---|---:|---:|---|',
]
for key,s in r['all_229_joint'].items():
 text.append(f"| {key} | {s['expected']} | {s['observed']} | 未验证（不是0%） |")
text += [
'没有任何已完成评分，因此不能声称已知错误被拦住、正确项被保留，不能用缺失结果计算通过率。单模型、开发/最终分项分母与null结果都在report.json。',
f"当前人工确认真实中文正例 **{r['human_positive_points']}**，距保底 {f['minimum']} 仍缺 **{r['gap_to_minimum']}**，距目标 {f['target']} 缺 **{f['target']-r['human_positive_points']}**。原池失败的结论保持，不因新增代码改变。",
'## 后续执行与未完成项',
'恢复同一冻结模型对的可用额度后，从本次冻结的开发输入继续。当前执行器默认拒绝重试失败台账，恢复时须显式实现/记录恢复操作，保留原失败历史及原提示词/切分，不另抽题或改结果。此处尚未完成恢复；不能把脚本名字当作真实完成。',
f"离线完整达标后才对全部 {len(read_rows(Path('.local/phase1/chinese-expansion-v2/dulemon/items.jsonl')))} 条DuLeMon候选重新整批双标，两份新标签完整且引用有效后再从未审共同keep池固定种子 {f['new_blind_sample_seed']} 独立抽 {72} 条。沿用原八列、原JSON来源、人工栏空白、乱序/不透明编号；不足不凑，盲审错误最多 {f['thresholds']['next_audit_max_errors']} 条。",
'额度恢复是当前外部阻塞。若要换模型仍需负责人明确确认，不能自动替换；补量仍等新盲审通过。当前没有新的审核表需要负责人填写。',
'未完成：离线效果验证、整批v3双标、独立新盲审、增量补量、真实中文保底规模、完整负例会话闸门、合成表裁判稳定备选及人工校准。ECD与困难集人工审核继续暂缓，不催办；查询版本和指标定义未改。',
'## 验证与证据',
f"完整检查：**{validation['pytest']} tests passed / {validation['seconds']}s**；ruff与strict mypy通过；foundation {validation['foundation']}。引用伪造、助手角色、错误source_id、空引用、重复来源、会话隔离、额度失败不计拦截且不触碰最终集/整批入口都有测试。",
'证据：report.json（脚本生成分母、输入/提示词/代码SHA、实际错误）；validation.log（完整检查）；prompt.txt（实际锁定提示词）。原始人工数据/请求/响应只在服务器.local，不进公开仓库。所有交付发当前群，不私发。',
'```bash\n# 首次冻结已完成，不重跑prepare覆盖\nwith-tencent uv run python scripts/run-evidence-v3.py offline\nuv run python scripts/run-evidence-v3.py report\nbash scripts/check.sh\nuv run python scripts/report-evidence-v3.py\n```',
'上述offline命令再次执行不会自动重试已有失败记录；恢复前先记录方案及具体恢复操作。报告生成不发模型请求。',
]
# Markdown table rows contiguous.
body='\n\n'.join(text)+'\n'
body=re.sub(r'(\|[^\n]*\|)\n\n(?=\|)',r'\1\n',body)
(OUT / 'delivery.md').write_text(body)
copy = ROOT / 'agent-memory阶段1标注规程v3与额度阻塞交接-2026-10-22.md'
shutil.copyfile(OUT / 'delivery.md',copy)
print(json.dumps({'report':str(copy),'tests':validation['pytest'],'status':r['status']}))
