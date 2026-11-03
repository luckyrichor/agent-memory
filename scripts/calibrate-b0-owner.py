"""Join immutable owner labels, audit judges, repeat a frozen 100; publish aggregates only."""
import argparse
import asyncio
import csv
import hashlib
import importlib.util
import json
import os
import random
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))
from agent_memory.evals.b0 import calibration_sample

BASE = REPO / '.local/phase2/b0/frozen-deepseek-20261026-v1'
RUN = BASE / 'recovery-run-2'
OUT = BASE / 'calibration-owner-20261027'
PUBLIC = REPO / 'docs/reports/phase2-b0-owner-calibration-2026-10-27'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    if path.is_relative_to(BASE):
        path.chmod(0o600)


def joined():
    filled = OUT / 'calibration-300-private_filled.csv'
    with filled.open(encoding='utf-8-sig', newline='') as stream:
        human = list(csv.DictReader(stream))
    with (RUN / 'calibration-300-private.csv').open(encoding='utf-8-sig', newline='') as stream:
        original = list(csv.DictReader(stream))
    expected = {r['item_id']: r for r in original}
    assert len(human) == len(expected) == len({r['item_id'] for r in human}) == 300
    assert {r['item_id'] for r in human} == set(expected)
    for row in human:
        assert row['human_correct'] in {'0', '1'} and row['human_reason'].strip()
        assert all(row[k] == expected[row['item_id']][k] for k in ('question', 'reference', 'answer'))
    h = {r['item_id']: r for r in human}
    manifest = json.loads((RUN / 'run-manifest.json').read_text())
    config = manifest['config']
    mapping = json.loads((RUN / 'calibration-mapping-private.json').read_text())
    cross = json.loads((RUN / 'cross-reference-private.json').read_text())
    assert len(cross) == len({r['row_id'] for r in cross}) == 300
    cross = {r['row_id']: r for r in cross}
    assert set(cross) == {r['row_id'] for r in mapping}
    result = []
    for row in mapping:
        item_id = 'c-' + digest([config['calibration_seed'], row['row_id'], config['baseline_configuration_id']])[:20]
        assert row['judge_model'] == 'glm-5.2' and type(row['judge_correct']) is bool
        assert cross[row['row_id']]['model'] == 'minimax-m3' and type(cross[row['row_id']]['correct']) is bool
        result.append({**row, 'item_id': item_id, 'human_correct': h[item_id]['human_correct'] == '1',
                       'human_reason': h[item_id]['human_reason'],
                       'minimax_correct': cross[row['row_id']]['correct']})
    return result, manifest


def simple(rows, key):
    pairs = [(r[key], r['human_correct']) for r in rows if type(r.get(key)) is bool]
    n = len(pairs)
    matrix = Counter(pairs)
    agree = sum(a == b for a, b in pairs)
    accuracy = agree / n if n else None
    pe = sum(sum(a == c for a, _ in pairs) * sum(b == c for _, b in pairs)
             for c in (False, True)) / n ** 2 if n else 1
    kappa = (accuracy - pe) / (1 - pe) if n and pe < 1 else None
    positives = sum(a for a, _ in pairs)
    return {'n': n, 'invalid': len(rows) - n, 'accuracy': accuracy, 'kappa': kappa,
            'confusion': {'judge0_human0': matrix[False, False], 'judge0_human1': matrix[False, True],
                          'judge1_human0': matrix[True, False], 'judge1_human1': matrix[True, True]},
            'false_positive_over_all': matrix[True, False] / n if n else None,
            'false_positive_over_judge_positive': matrix[True, False] / positives if positives else None,
            'judge_positive_n': positives, 'false_negative_over_all': matrix[False, True] / n if n else None,
            'adoptable_on_this_calibration': n == 300 and ((kappa is not None and kappa >= .7) or accuracy >= .9)}


def metric(rows, key, bootstrap=False):
    value = simple(rows, key)
    if not bootstrap:
        return value
    groups = defaultdict(list)
    for row in rows:
        groups[row['dataset'], row['conversation_id']].append(row)
    keys = sorted(groups)
    rng = random.Random(2026102701)
    samples = defaultdict(list)
    for _ in range(1000):
        sample = [r for _ in keys for r in groups[rng.choice(keys)]]
        s = simple(sample, key)
        for name in ('accuracy', 'kappa', 'false_positive_over_all', 'false_positive_over_judge_positive'):
            if s[name] is not None:
                samples[name].append(s[name])
    def interval(values):
        values = sorted(values)
        return [values[int((len(values) - 1) * .025)], values[int((len(values) - 1) * .975)]] if values else None
    value['ci95'] = {k: interval(v) for k, v in samples.items()}
    value['ci_method'] = '1000 percentile resamples of dataset+conversation clusters within the fixed stratified calibration sample; conditional diagnostic, not dev-population CI'
    value['clusters'] = len(keys)
    return value


def strata(rows, key, fields):
    groups = defaultdict(list)
    for row in rows:
        groups['/'.join(str(row[f]) for f in fields)].append(row)
    return {name: metric(items, key) for name, items in sorted(groups.items())}


def stability(records, selected, model):
    values = {(r['row_id'], r['repeat']): r['correct'] for r in records if r['model'] == model}
    complete = []
    for row in selected:
        triplet = [values.get((row['row_id'], k)) for k in range(3)]
        if all(type(v) is bool for v in triplet):
            complete.append(triplet)
    changed = sum(len(set(v)) > 1 for v in complete)
    disagreements = sum(a != b for v in complete for a, b in ((v[0], v[1]), (v[0], v[2]), (v[1], v[2])))
    return {'planned_rows': 100, 'new_repeats_per_row': 3, 'complete_rows': len(complete),
            'changed_any_of_three_n': changed, 'changed_any_of_three_ratio': changed / len(complete) if complete else None,
            'pairwise_disagreement_n': disagreements, 'pairwise_denominator': len(complete) * 3,
            'pairwise_disagreement_ratio': disagreements / (len(complete) * 3) if complete else None,
            'valid_repeat_calls': sum(type(v) is bool for v in values.values()),
            'invalid_repeat_calls': sum(type(v) is not bool for v in values.values())}


def report():
    rows, manifest = joined()
    chosen = calibration_sample(rows, 100, seed=2026102702)
    repeat_file = OUT / 'repeats-private.json'
    repeats = json.loads(repeat_file.read_text()) if repeat_file.exists() else []
    judges = {}
    for model, key in [('glm-5.2', 'judge_correct'), ('minimax-m3', 'minimax_correct')]:
        judges[model] = {'overall': metric(rows, key, True), 'by_type': strata(rows, key, ['category']),
            'by_system': strata(rows, key, ['system']), 'by_type_system': strata(rows, key, ['category', 'system']),
            'by_dataset': strata(rows, key, ['dataset']), 'flow_only': strata(rows, key, ['flow_only']),
            'self_consistency': stability(repeats, chosen, model),
            'disagreement_types': dict(Counter(r['category'] for r in rows if r[key] != r['human_correct']))}
        groups = judges[model]['by_type_system']
        worst = min((v['accuracy'] for v in groups.values() if v['n']), default=None)
        judges[model]['worst_type_system'] = {k: v for k, v in groups.items() if v['accuracy'] == worst}
    result = {'created_beijing': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
        'baseline_configuration_id': manifest['config']['baseline_configuration_id'],
        'baseline_commit': manifest['baseline_commit'],
        'harness_base_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
        'uncommitted': True, 'owner_labels_sha256': sha(OUT / 'calibration-300-private_filled.csv'),
        'original_export_sha256': sha(RUN / 'calibration-300-private.csv'),
        'mapping_sha256': sha(RUN / 'calibration-mapping-private.json'),
        'cross_reference_sha256': sha(RUN / 'cross-reference-private.json'),
        'prompt_hashes': {str(p.relative_to(REPO)): sha(p) for p in [REPO / 'docs/evals/prompts/judge-v1.txt', REPO / 'docs/evals/prompts/b0-lme-judge-rubrics-v1.json']},
        'validation': {'rows': len(rows), 'unique_ids': len({r['item_id'] for r in rows}),
            'frozen_fields_equal': True, 'human_positives': sum(r['human_correct'] for r in rows),
            'human_negatives': sum(not r['human_correct'] for r in rows), 'reasons_all_filled': True},
        'judge_models': judges, 'round': 1, 'max_rounds': 3,
        'gate': 'kappa >= 0.7 OR accuracy >= 0.90; all300 valid; latest explicit owner rule',
        'prompt_revised': False,
        'backup_provenance': 'Reuse the completed same300 minimax-m3 cross-reference judgments under frozen v1, exact row_id join, no relabel/cherry-pick; backup and cross-reference are the SAME model, not independent evidence',
        'selection': '300 stratified by category/system/primary judge outcome; 100 fixed seed2026102702 from SAME300 and same strata; repeats3 new calls per model, not original run counts',
        'self_consistency_complete': all(v['self_consistency']['complete_rows'] == 100 for v in judges.values()),
        'phase2_accepted': False, 'stage3_started': False,
        'metric_scope': 'Judge calibration validates answer-grading reliability only; does not validate missing EX/LC/RT/CX/RL/SC/PF adapters or candidate activation',
        'population_correction': 'No naive accuracy multiplier or global correction: outcome/type/system stratified calibration is not a simple random population sample; no unweighted300 CI claimed as full1560 system accuracy; original E1 kept with provenance and calibration attached',
        'remaining': ['independent cross-region PF host and measurements', 'missing functional observation adapters and true tokenizer coverage', 'phase2 acceptance; no automatic phase3'],
        'bias': 'DeepSeek同时是金标准标注模型之一，答题/抽取与标注同厂商可能使抽取指标偏高，双厂商共同保留已部分抵消；ECD客服领域不代表一般对话；程序构造题只作流程验证'}
    if not result['self_consistency_complete']:
        result['remaining'].insert(0, '100 rows x3 fresh repetitions for BOTH judges pending/incomplete; invalids separate')
    PUBLIC.mkdir(parents=True, exist_ok=True)
    write(PUBLIC / 'calibration-report.json', result)
    text = ['# B0裁判人工校准报告（阶段2未验收）', '',
        f"时间：{result['created_beijing']}；agent-memory@{result['harness_base_commit'][:7]}，含未提交修改；业务B0@{result['baseline_commit'][:7]}。", '',
        '## 数据与方法', '',
        '冻结开发抽样B0；校准300条按题型、系统组、原裁判正确/错误分层，来自同一1560实验行；人工0/1逐item_id关联、原文/答案/理由不改。非简单随机抽样，下面总体数指校准样本，不冒充全部开发集。95%区间用数据集+会话聚类bootstrap1000次，是固定分层样本内诊断。',
        '对照：主裁判GLM5.2、备选MiniMax3对同一负责人人工标签；模型输入仅问题/参考/答案和冻结rubric，不给系统组、人工结果或理由。', '',
        '## 主备裁判与混淆矩阵', '',
        '| 裁判 | n | 准确率 | κ | 判0/人工0 | 判0/人工1 | 判1/人工0 | 判1/人工1 | 错判为对/全部 | 错判为对/裁判判对 | 采用门槛 |',
        '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|']
    for model, d in judges.items():
        v = d['overall']; c = v['confusion']
        text.append(f"| {model} | {v['n']} | {v['accuracy']:.4%} | {v['kappa']:.6f} | {c['judge0_human0']} | {c['judge0_human1']} | {c['judge1_human0']} | {c['judge1_human1']} | {v['false_positive_over_all']:.4%} | {v['false_positive_over_judge_positive']:.4%} | {'通过' if v['adoptable_on_this_calibration'] else '不通过/不得正式采用'} |")
        text.append(f"\n{model} 95%聚类区间：{json.dumps(v['ci95'], ensure_ascii=False)}。")
    text += ['', '门槛按负责人本次明确口径：κ≥0.7或准确率≥90%；不适用此前更严的κ单闸门。本轮通过则不改提示词、不启动无必要的再校准；失败须版本化修订、整批重判并记录同批复用，最多三轮，仍失败改纯人工。', '', '## 分题型、系统组与最差分层', '']
    for model, d in judges.items():
        for label, field in [('题型', 'by_type'), ('系统组', 'by_system'), ('题型×系统组', 'by_type_system')]:
            text += ['', f'### {model} / {label}', '', '| 层 | n | 一致率 |', '|---|---:|---:|']
            text += [f"| {k} | {v['n']} | {v['accuracy']:.4%} |" for k, v in d[field].items()]
        text += ['', '**最差题型×系统层（小样本须看n）**：' + json.dumps(d['worst_type_system'], ensure_ascii=False),
            '分歧题型计数：' + json.dumps(d['disagreement_types'], ensure_ascii=False)]
    text += ['', '## 同批100条三次新判分自一致性', '']
    for model, d in judges.items():
        text.append(model + '：' + json.dumps(d['self_consistency'], ensure_ascii=False))
    text += ['', '变化比例=三次中任意一次不同的条目数/三次均有效条目数；另列三对判分两两不一致率。无效输出不算对错，也不算稳定。原B0判分不充作三次之一。', '',
        '## B0使用范围、区间与局限', '', result['backup_provenance'], result['population_correction'], result['metric_scope'], result['bias'],
        '两模型交叉参照不能充当第二个独立MiniMax验证；MiniMax作为标注厂商的构造题仍不放行其作正式独立裁判。主裁判人工门槛通过不等于全部指标或阶段2验收通过。', '',
        '## 未完成项', ''] + ['- ' + v for v in result['remaining']]
    (PUBLIC / 'calibration-report.md').write_text('\n'.join(text) + '\n')
    aggregate = RUN / 'aggregate/report.json'
    b0 = json.loads(aggregate.read_text())
    b0['owner_judge_calibration'] = result
    b0['human_calibration_received'] = True
    b0['formal_quality_scores_allowed'] = judges['glm-5.2']['overall']['adoptable_on_this_calibration']
    b0['remaining'] = result['remaining']
    write(aggregate, b0)
    delivery = RUN / 'aggregate/delivery.md'
    old = delivery.read_text()
    marker = '\n<!-- owner-calibration-current -->\n'
    old = old.split(marker)[0]
    delivery.write_text(old + marker + '\n更正/更新：负责人300条已收到并完成关联；此前“人工结果未收到”为历史状态。校准聚合如下，不包含人工逐条标签或理由。\n\n' + '\n'.join(text) + '\n')
    print(json.dumps({'judges': {m: d['overall'] for m, d in judges.items()},
        'self_consistency_complete': result['self_consistency_complete']}, ensure_ascii=False), flush=True)
    return rows, chosen, result


async def repeat_measurements(chosen):
    spec = importlib.util.spec_from_file_location('b0_calibration_runtime', REPO / 'scripts/run-b0.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    config = json.loads((RUN / 'run-manifest.json').read_text())['config']
    config['resume_roots'] = []
    calls = OUT / 'fresh-repetition-calls'
    calls.mkdir(exist_ok=True, mode=0o700)
    checkpoint = OUT / 'repeats-private.json'
    records = json.loads(checkpoint.read_text()) if checkpoint.exists() else []
    existing = {(r['model'], r['row_id'], r['repeat']) for r in records}
    io = module.ModelIO(calls, config=config)
    # A rerun uses a fresh call directory/index to preserve every previous raw call.
    if (calls / 'usage.jsonl').exists():
        io.index = max(json.loads(s)['call_id'] for s in (calls / 'usage.jsonl').read_text().splitlines())
    sem = asyncio.Semaphore(4)
    async def one(row, model, repeat):
        if (model, row['row_id'], repeat) in existing:
            return
        async with sem:
            try:
                value = await io.grade(row, model)
                error = None
            except RuntimeError as exc:
                value, error = None, str(exc)
            records.append({'model': model, 'row_id': row['row_id'], 'repeat': repeat,
                            'correct': value, 'error': error})
            write(checkpoint, records)
            if len(records) % 50 == 0:
                print(json.dumps({'fresh_repeat_calls_closed': len(records), 'planned': 600}), flush=True)
    try:
        await asyncio.gather(*(one(row, model, repeat) for repeat in range(3)
            for row in chosen for model in ('glm-5.2', 'minimax-m3')))
    finally:
        await asyncio.gather(*(client.aclose() for client in io.clients.values()))


def handoff(result, finished):
    now = result['created_beijing']
    note = f"\n\n## {now} 负责人300条裁判校准\n\n由Codex记录，agent-memory@{result['harness_base_commit'][:7]}加未提交修改。人工300标签核验/冻结字段比对通过，原文件SHA256已记录。主裁判与备选均为第1轮冻结提示词；备选复用同批完整cross-reference，非独立第二模型。"
    for model, value in result['judge_models'].items():
        v = value['overall']
        note += f" {model}：n={v['n']}，准确率{v['accuracy']:.6f}，κ={v['kappa']:.6f}，门槛通过={v['adoptable_on_this_calibration']}。"
    note += f" 同批100×3新判分完成={result['self_consistency_complete']}。报告`docs/reports/phase2-b0-owner-calibration-2026-10-27/calibration-report.md`；不外发原文/人工标签/理由。阶段2未验收，PF与缺失指标仍待完成，不进入阶段3；飞书Wiki按用户要求暂缓。\n"
    for name in ['docs/progress.md', 'docs/devlog/2026-10-26-phase2-b0-frozen-deepseek-rebuild.md']:
        path = REPO / name
        path.write_text(path.read_text() + note)
    path = REPO / 'AGENTS.md'
    text = path.read_text()
    start = text.index('<!-- B0_RUN_STATE_START -->')
    end = text.index('<!-- B0_RUN_STATE_END -->', start) + len('<!-- B0_RUN_STATE_END -->')
    text = text[:start] + '<!-- B0_RUN_STATE_START -->\n' + note + '\n<!-- B0_RUN_STATE_END -->' + text[end:]
    path.write_text(text)
    state_path = REPO / 'docs/evals/b0-current.json'
    state = json.loads(state_path.read_text())
    state.update(human_calibration_received=True, judge_calibration_report=str(PUBLIC.relative_to(REPO) / 'calibration-report.json'),
        self_consistency_complete=result['self_consistency_complete'], status='calibration measured; phase2 still incomplete' if finished else 'owner calibration joined; fresh100x3 repetitions running')
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + '\n')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--repeat', action='store_true')
    parser.add_argument('--send', action='store_true')
    args = parser.parse_args()
    original_hash = sha(OUT / 'calibration-300-private_filled.csv')
    _, chosen, result = report()
    handoff(result, False)
    if args.repeat:
        asyncio.run(repeat_measurements(chosen))
        _, _, result = report()
        assert sha(OUT / 'calibration-300-private_filled.csv') == original_hash
        handoff(result, True)
    if args.send:
        sent = subprocess.run([os.environ['LARK_CLI_PATH'], 'im', '+messages-send', '--as', 'bot',
            '--chat-id', 'oc_e7156f4a7fa19da571d73b10169cd92f', '--file',
            str((PUBLIC / 'calibration-report.md').relative_to(REPO)), '--idempotency-key',
            'b0-owner-calibration-20261027-' + str(result['self_consistency_complete'])],
            capture_output=True, text=True)
        write(OUT / 'delivery-private.json', {'returncode': sent.returncode, 'stdout': sent.stdout, 'stderr': sent.stderr})
        print(json.dumps({'aggregate_delivery_exit': sent.returncode}), flush=True)


if __name__ == '__main__':
    main()
