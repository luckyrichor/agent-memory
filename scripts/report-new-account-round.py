"""Generate a public handoff from private evidence; ECD section stays byte-identical."""
import difflib
from collections import Counter
import json
import platform
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from agent_memory.evals.evidence_v3 import read_rows, sha

ROOT = Path('.local/phase1/round3/new-accounts-v1')
OLD = Path('.local/phase1/round3/temporal-v1')
OUT = Path('docs/reports/phase1-round3-new-accounts-2026-10-22')


def load(path):
    return json.loads(path.read_text())


def vendor(model):
    for prefix, name in [('deepseek','DeepSeek'),('hy','Tencent'),('hunyuan','Tencent'),('glm','Zhipu'),('mimo','Xiaomi'),('minimax','MiniMax'),('kimi','Moonshot'),('qwen','Alibaba')]:
        if model.startswith(prefix):
            return name
    raise ValueError('Unknown model vendor: '+model)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    planning = load(ROOT/'adoption-and-plan.json')
    root = ROOT/'increment-batches-v6'
    final = load(root/'report.json') if (root/'report.json').exists() else None
    batches = load(root/'batch-registry.json') if (root/'batch-registry.json').exists() else load(OLD/'increment-batches-single-packet-v1/batch-registry.json')
    screen = load(OLD/'screen/report.json')
    selected = set(load(root/'manifest.json')['available_indices'][:500]) if (root/'manifest.json').exists() else set()
    for manifest_path in root.glob('cohort-*/batch-*/manifest.json'):
        selected.update(load(manifest_path)['new_indices'])
    if final:
        final['controller_remaining_unused_dialogues_raw'] = final['remaining_unused_dialogues']
        final['remaining_unused_dialogues'] = len(load(root/'manifest.json')['available_indices'])-len(selected)
        final['selected_incomplete_dialogues'] = len(selected)-final['conversations']
    annotations = []
    annotation_unknown = 0
    for path in sorted(ROOT.glob('annotation-preflight*/*/*/report.json')):
        row = load(path)
        results = [load(p) for p in sorted(path.parent.glob('*-result.json'))]
        unrecorded = sum(bool(r.get('error_type') in ('RemoteProtocolError','ConnectError','ReadTimeout','WriteTimeout','ConnectTimeout') and not r['attempts']) for r in results)
        row['qualification_variant'] = next(part for part in path.parts if part.startswith('annotation-preflight'))
        row['raw_report_calls'] = row['calls']
        row['calls'] += unrecorded
        row['transport_attempts_without_response_recorded_late'] = unrecorded
        row['http_counts'] = dict(Counter(str(a['http']) for r in results for a in r['attempts'] if 'http' in a))
        row['error_types'] = dict(Counter(r['error_type'] for r in results if r.get('error_type')))
        row['provider_error_codes'] = dict(Counter(str((load(p).get('error') or {}).get('code')) for p in path.parent.glob('*-response-*-private.json') if isinstance(load(p),dict) and load(p).get('error')))
        annotation_unknown += unrecorded + sum(bool(a.get('response_usage_unknown')) for r in results for a in r['attempts'])
        annotations.append(row)
    judges = []
    for path in sorted([*(ROOT/'judge-preflight').rglob('*-summary.json'),*(ROOT/'judge-repair').rglob('*-summary.json')]):
        row = load(path)
        account = 'ark-secondary' if 'ark-secondary' in path.parts else 'tokenhub-secondary'
        control = ROOT/'judge-controls'/account/(row['model']+'.json')
        row['qualification_variant'] = 'transport-repair' if 'judge-repair' in path.parts else 'original'
        row.update(preflight_path=str(path),actual_call_path=str(control),account=account, vendor=vendor(row['model']), provider='Ark' if account=='ark-secondary' else 'TokenHub', evidence_sha256=sha(path))
        row['judge_prompt_controls'] = load(control) if control.exists() else None
        row['eligible'] = row['preflight_pass'] and bool(row['judge_prompt_controls'] and row['judge_prompt_controls'].get('passed') and row['judge_prompt_controls'].get('generic_preflight_sha256')==sha(path))
        judges.append(row)
    pools = {}
    for name, annotation_vendors in [('old-pool',['DeepSeek','Tencent']),('new-pool',sorted({vendor(m) for b in batches for m in b['models']}))]:
        exclude = set(annotation_vendors)|{'ByteDance'}
        eligible = [r for r in judges if r['eligible'] and r['vendor'] not in exclude]
        eligible.sort(key=lambda r: (r['model']!='glm-5.2',r['model']!='mimo-v2.6-flash',r['account'],r['model']))
        records = [{k:r[k] for k in ('model','vendor','provider','account','evidence_sha256','preflight_path','actual_call_path')} for r in eligible]
        pools[name] = {'annotation_vendors':annotation_vendors,'excluded_vendors':sorted(exclude),'primary':records[0] if records else None,'backups':records[1:],'backup_gap':max(0,1-max(0,len(records)-1)),'human_calibrated':False,'formal_scores_allowed':False}
    calls = tokens = cache = 0
    for path in sorted(root.glob('**/ledger.json')):
        for row in load(path):
            calls += len(row.get('attempts',[]))
            tokens += (row.get('usage') or {}).get('total_tokens',0)
            cache += bool(row.get('cache_hit'))
    annotation_calls = sum(r['calls'] for r in annotations)
    annotation_tokens = sum(r['reported_tokens'] for r in annotations)
    judge_calls = judge_tokens = 0
    for path in sorted((ROOT/'judge-preflight').rglob('progress.json')):
        for row in load(path):
            judge_calls += len(row['attempts'])
            judge_tokens += (row.get('usage') or {}).get('total_tokens',0)
    for path in sorted((ROOT/'judge-repair').rglob('new-attempts.json')):
        for row in load(path):
            judge_calls += 1
            judge_tokens += (row.get('usage') or {}).get('total_tokens',0)
    controls_calls = controls_tokens = 0
    for path in sorted((ROOT/'judge-controls').glob('*/*.json')):
        for row in load(path)['calls']:
            controls_calls += 1
            controls_tokens += (row.get('usage') or {}).get('total_tokens',0)
    interruption = load(ROOT/'interrupted-preflight-history/report.json')
    generic_unknown = sum(1 for path in (ROOT/'judge-preflight').rglob('progress.json') for r in load(path) for a in r['attempts'] if a.get('http_status') is None and a.get('error_type'))
    unknown = sum(r['possibly_inflight_without_response'] for r in interruption['records']) + annotation_unknown + generic_unknown
    plan = Path('docs/plans/2026-10-22-agent-memory-interview-plan-v3.md')
    prior = Path('docs/plans/2026-10-21-agent-memory-interview-plan-v2.md')
    assert sha(plan) == load(Path('docs/evals/phase1-new-accounts-policy-v1.json'))['plan_sha256']
    protected = load(ROOT/'ecd-unchanged-hashes.json')
    for name, value in protected.items():
        assert sha(Path(name)) == value, 'ECD changed'
    old_delivery = Path('docs/reports/phase1-round3-temporal-2026-10-22/delivery.md').read_text()
    ecd_section = old_delivery.split('## ECD负样本小金标准\n',1)[1].split('## 裁判池影响',1)[0]
    code = subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
    dirty = bool(subprocess.check_output(['git','status','--porcelain'],text=True).strip())
    validation = ROOT/'check-final.log'
    test_text = validation.read_text() if validation.exists() else ''
    test_match = re.search(r'(\d+) passed in ([\d.]+)s',test_text)
    assert test_match and 'All checks passed!' in test_text and 'no issues found' in test_text and 'tenant_leaks=0 deleted_memory_hits=0' in test_text, 'full final gates required'
    report = {
        'created_at':datetime.now(UTC).isoformat(),'source_commit':code,'uncommitted_changes_at_generation':dirty,
        'plan':str(plan),'plan_sha256':sha(plan),'policy':load(Path('docs/evals/phase1-new-accounts-policy-v1.json')),
        'planning':planning,'old_audit':{k:screen[k] for k in ('audit_precision','audit_errors','maximum_errors','error_types')},
        'old_temporal_screen_reference_only':{k:screen[k] for k in ('pool_temporary_removed','known_errors_identified','human_positive_falsely_removed','human_positive_denominator')},
        'batches':batches,'increment':final,'annotation_preflight':annotations,'judge_preflight':judges,'judge_pools':pools,
        'usage_new_round':{'annotation_preflight_calls':annotation_calls,'annotation_preflight_reported_tokens':annotation_tokens,'judge_preflight_calls':judge_calls,'judge_preflight_reported_tokens':judge_tokens,'judge_prompt_control_calls':controls_calls,'judge_prompt_control_reported_tokens':controls_tokens,'annotation_calls':calls,'annotation_reported_tokens':tokens,'cached_response_replays_not_new_calls':cache,'known_total_post_calls':annotation_calls+judge_calls+controls_calls+calls,'reported_total_tokens':annotation_tokens+judge_tokens+controls_tokens+tokens,'possible_interrupted_unknown_usage_calls':unknown},
        'validation':{'pytest_passed':int(test_match[1]),'pytest_seconds':float(test_match[2]),'ruff':True,'strict_mypy':True,'foundation':True,'log_sha256':sha(validation)},
        'token_projection':load(ROOT/'token-projection.json'),'ecd_unchanged_hashes':protected,
        'phase1_accepted':False,'new_pool_adopted':0,
    }
    (OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    (OUT/'plan-diff.patch').write_text(''.join(difflib.unified_diff(prior.read_text().splitlines(True),plan.read_text().splitlines(True),fromfile=str(prior),tofile=str(plan))))
    (OUT/'validation.log').write_text(test_text)
    p=planning
    lines = [
        '# agent-memory 阶段1第三轮：旧池采纳、新密钥预检与增量补量',
        f"生成：{report['created_at']}；分析源码：`{code}`；生成时有未提交改动：{dirty}。执行工具 Codex；具体 Codex 模型版本未核实。环境：{platform.platform()}。阶段1仍未验收，不进入阶段2。",
        '## 执行版本与差异',
        f"已完整重读方案 `{plan}`，SHA256 `{sha(plan)}`；原文和署名保留。本轮重读相对上一轮保存的v3原件字节不变；旧v2到v3逐行差异见plan-diff.patch。",
        'v3新增两层记忆、PAL-Set后续可选和自动换型。当前按负责人最新消息执行四项覆盖：旧池不采用时效性筛选；采纳旧池与人工正例并集后补到700；新密钥重新预检；未完成第4批两侧全部作废重做。旧角色表的两个裁判备选按后续至少一个执行，旧DS/MiMo固定组合按已授权换型执行。ECD原件写直接人工标注，实际披露仍为AI草稿加人工确认；旧κ目标不以程序uncertain或本轮通过盲审冒充达标，阶段1仍未验收。原件未被静默改写。',
        '## 当前规模与质量口径',
        f"旧池 {p['old_pool_original']} 扣除人工错误 {p['known_errors_removed']}，采纳 {p['old_pool_adopted']}；逐条人工确认 {p['human_confirmed']}；重叠 {p['overlap_human_old']}；去重可靠规模 **{p['base_reliable_union']}**。其中仅模型标注、抽检整池采纳但未逐条人工确认 {p['old_pool_model_only']}，不得冒称全部人工标签。距700缺 {p['base_gap_700']}，距1500缺 {p['base_gap_1500']}。",
        f"旧盲审 {screen['audit_precision']['numerator']}/{screen['audit_precision']['denominator']}，精度 {screen['audit_precision']['value']:.4%}，会话级聚类重采样95%区间 [{screen['audit_precision']['ci95'][0]:.4%}, {screen['audit_precision']['ci95'][1]:.4%}]；{screen['audit_precision']['n']}个会话，1000次，种子42；错误{screen['audit_errors']}，压线通过。错误均为临时状态。区间不是额外质量门，也不保证整池最多仅三个未知错误。",
        f"旧池不应用时效性筛选。历史筛选仅参考：旧池临时标记 {screen['pool_temporary_removed']}，识别已知临时错误 {screen['known_errors_identified']}/{screen['audit_errors']}，人工正例误剔除 {screen['human_positive_falsely_removed']}/{screen['human_positive_denominator']}；这些不从旧池或人工正例中剔除。新增池继续任一侧临时即不得keep。合计仅做规模去重汇总，时效性相关误差率按旧池/新增池分别报告，不混报为同一筛选规则。",
        '## 补量目标、预算与库存',
        f"基于已完成 {p['completed_new_dialogues']} 段、{p['completed_new_candidates']} 候选、{p['completed_new_joint_keep']} 共同保留：新增目标 {p['target_new_joint_keep']}（含最多三条最终盲审错误的记账预留），初始还缺 {p['new_joint_gap']}。预留不是统计保证，最终仍由独立72条盲审把关。",
        f"条件外推：共同保留率 {p['conditional_projection']['joint_yield']:.4%}，初始预计还需 {p['conditional_projection']['additional_candidates']} 候选、{p['conditional_projection']['additional_dialogues']} 对话（含须重做{p['redo_dialogues']}段，条件估计额外未用对话{max(0,p['conditional_projection']['additional_dialogues']-p['redo_dialogues'])}段；固定整批执行时按批舍入）、双侧每请求8条约 {p['conditional_projection']['two_side_packet8_calls']} 次；若腾讯侧单条则约 {p['conditional_projection']['packet8_plus_packet1_calls']} 次。按历史真实响应均值约 {report['token_projection']['additional_token_estimate']} token，不含预检、重试、换型重标和批次舍入；不是实际产出或额度保证。",
        f"本轮开始未用库存 {p['unused_dialogues']} 段；另有此前已选但未完成的 {p['redo_dialogues']} 段整批重做。新取样种子 {p['supplement_seed']}，继承原会话切分，只用BOTH/train且字段完整的未用对话。到达目标或用尽库存即停。",
        '## 新密钥预检',
        'MiMo原始98/100中的两项是无响应连接中断，仅对同两个请求有限重试，原其他104响应不重发，独立修复记录保留；没有重采不合格模型答案。密钥从服务器原配置按secondary账户注入，不写日志、仓库或报告。两家目录HTTP200仅表示目录可读，不代替实际调用。原预检中断后从真实已保存响应恢复，不重发已完成的检查；可能在途无响应的调用单列未知用量。',
        '|渠道账户|标注候选/预检版本/输出方式|格式有效/分母|五次一致|关闭思考观测|通过|',
        '|---|---|---:|---|---|---|',
    ]
    for row in annotations:
        lines.append(f"|{row['account']}|{row['model']} / {row['qualification_variant']} / {row.get('transport_response_format','default')}|{row['format_valid']}/{row['format_n']}|{row['consistent_5']}|{row['observed_disabled_thinking']}|{row['passed']}|")
    lines += ['格式门槛仍为至少99/100；五次一致指label与temporal判定一致，不是理由逐字节一致。100个不同虚构输入只验证格式，不作质量证据。未通过者不能进入本轮标注组合。方舟新增账户实际调用返回404，已存错误码ModelNotOpen，不是余额不足结论；未自行开通模型、充值或修改计费。', '## 完整新增批次', '|批次|模型组合|对话|候选|共同保留|临时标记|引用无效|结构无效|','|---|---|---:|---:|---:|---:|---:|---:|']
    for batch in batches:
        lines.append(f"|{batch['batch']}|{' + '.join(batch['models'])}|{batch['conversations']}|{batch['candidates']}|{batch['joint_keep']}|{batch['temporal_removed']}|{batch['citation_invalid']}|{batch['schema_invalid']}|")
    if final:
        lines.append(f"新增完整冻结 {final['conversations']} 段、{final['candidates']} 候选，合格去重共同保留 **{final['joint_keep']}**；原始共同保留 {final['raw_joint_keep']}，历史/内容重复/调试排除 {final['dedup_or_historical_removed']}（全候选分母）。新增目标达成={final['target_reached']}；库存未用 {final['remaining_unused_dialogues']}。新增采纳仍为0，当前可靠规模仍为{p['base_reliable_union']}。")
        lines.append(f"本次关闭={final['complete']}；阻塞（null表示未记录阻塞）：{json.dumps(final.get('blocked'),ensure_ascii=False)}。旧第4批两侧结果不拼接、不缓存重放；新批次失败时整侧换型重做，已完整冻结批次保留各自来源。")
        if final.get('audit'):
            audit=final['audit']
            lines.append(f"补量已完成，独立盲审导出 {audit['sample']} 条/{audit['conversations']} 会话，新种子{audit['seed']}，历史审核/开发/最终/调试条目重叠0。原八列、原source JSON、人工两栏空白、不透明编号、顺序打乱；审核表SHA256 `{audit['files']['audit-blind.csv']}`。等待负责人核对，错误不超过{audit['maximum_errors']}条才采纳新增池；通过且最多三错时并集记账规模至少 {p['base_reliable_union']+final['joint_keep']-audit['maximum_errors']}，目前不能宣称已达标。新池精度与区间待人工回填。")
        else:
            lines.append('补量尚未完成，未发新增72条盲审；部分结果不进入可靠规模。')
    lines += ['临时标记、引用无效、结构无效可重叠，不相加；程序拒绝为uncertain不当作模型语义标签算κ。标签仍经原精确source_id、user角色和原话子串校验。', '## ECD负样本小金标准',ecd_section.rstrip(), '## 裁判池：按旧池和新增池分别冻结', '|数据表|实际标注厂商|主裁判|备选|备选缺口|','|---|---|---|---|---:|']
    for name,pool in pools.items():
        main=pool['primary']
        lines.append(f"|{name}|{'、'.join(pool['annotation_vendors'])}|{main['provider']+'/'+main['model'] if main else '缺失'}|{'、'.join(r['provider']+'/'+r['model'] for r in pool['backups']) or '缺失'}|{pool['backup_gap']}|")
    lines += ['答题厂商为ByteDance。旧池时效性筛选未用于采纳，因此参考筛选用过Zhipu不再使旧表排除Zhipu；实际标注仍为DeepSeek/Tencent。新增表按各已完成批实际标注厂商并集排除。目录online不等于通过预检，预下线GLM-5V和已下线型号未恢复；主备尚未做人工校准，不能发布正式阶段2评分。', '|渠道账户|裁判候选/预检版本|格式有效/分母|五次一致|关闭思考观测|通用预检|裁判提示词控制|','|---|---|---:|---|---|---|---|']
    for row in judges:
        lines.append(f"|{row['account']}|{row['model']} / {row['qualification_variant']}|{row['format_valid']}/{row['format_n']}|{row['consistent_5']}|{row['observed_disabled_thinking']}|{row['preflight_pass']}|{bool(row['judge_prompt_controls'] and row['judge_prompt_controls'].get('passed'))}|")
    u=report['usage_new_round'];v=report['validation']
    lines += ['## 用量、测试与复现',f"仅本轮已知POST {u['known_total_post_calls']}，响应报告token {u['reported_total_tokens']}，缓存重放 {u['cached_response_replays_not_new_calls']} 不算新调用；另有中断可能在途、usage未知 {unknown} 次，不当作0费用。旧轮用量保留在历史报告，不重复算成本轮。未查询余额、未充值、未开后付费、未修改用量上限。",f"全量门禁：pytest {v['pytest_passed']} passed/{v['pytest_seconds']}秒，ruff通过，strict mypy通过，foundation零泄漏/零删除命中门通过。原日志validation.log。",'复现汇总：`uv run python scripts/prepare-new-account-round.py`；`uv run python scripts/report-new-account-round.py`。真实运行使用`with-llm-account.py tokenhub-secondary .venv/bin/python scripts/run-temporal-batch-cohorts-v6.py`；已有冻结目录不覆盖，失败历史不删除。原始数据、模型响应、审核映射仅服务器.local；公开仅方法、哈希、指标。','## 未完成与范围','- 新增盲审等待真实负责人回填，通过前不计新增可靠规模；阶段1没有自动验收。','- 裁判人工校准未做；技术池可用export-new-account-judge-pools.py导出到运行入口，run-judge-table.py支持显式--policy及old-pool/new-pool；未校准的主备仍由原加载器硬拒绝正式评分。缺口按表如实保留。','- 完整负样本会话数量与占比双闸门未共同确认；ECD系统误抽评测未做。','- 中文查询三类程序构造题仍为“流程验证，不作质量证据”，阶段2单列；不以高分证明真实中文质量。','- 其他阶段1历史证据（基准导入召回、查询、合成审计）沿用原冻结报告，本轮未重跑；见上一轮交接及第三轮收尾报告。没有进入阶段2或处理其他项目。']
    text=''.join(('\n' if i and line.startswith('|') and lines[i-1].startswith('|') else '\n\n' if i else '')+line for i,line in enumerate(lines))+'\n'
    assert text.split('## ECD负样本小金标准\n\n',1)[1].split('## 裁判池：',1)[0].rstrip()==ecd_section.rstrip()
    (OUT/'delivery.md').write_text(text)
    registry={'basis':'owner-approved-old-pool-union-human','individually_human_confirmed':p['human_confirmed'],'old_audited_model_pool':p['old_pool_adopted'],'old_model_only_not_individually_confirmed':p['old_pool_model_only'],'human_old_overlap':p['overlap_human_old'],'accepted_union':p['base_reliable_union'],'old_temporal_screen_applied':False,'new_pool_adopted':0,'phase1_accepted':False,'items_sha256':sha(ROOT/'accepted-base-union-private.jsonl'),'provenance_sha256':sha(ROOT/'accepted-base-provenance-private.json'),'owner_message':report['policy']['owner_message']}
    Path('docs/evals/reliable-chinese-current.json').write_text(json.dumps(registry,ensure_ascii=False,indent=2)+'\n')
    Path('docs/evals/judge-pools-new-accounts-v1.json').write_text(json.dumps(pools,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'source_commit':code,'base_reliable_union':p['base_reliable_union'],'new_pool_adopted':0,'output':str(OUT)}))


if __name__ == '__main__':
    main()
