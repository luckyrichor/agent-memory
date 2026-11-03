"""Dual-model semantic extraction assessment; pending task-specific owner calibration."""
import asyncio
import argparse
import csv
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path

import httpx

from agent_memory.evals.metrics import ratio

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'scripts'))
from b0_accounts import credential

ROOT = REPO / '.local/phase2/b0/completion-20261028/extraction'
RUN = REPO / '.local/phase2/b0/frozen-deepseek-20261026-v1/recovery-run-2'


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_lines(path):
    return [json.loads(s) for s in path.read_text().splitlines() if s.strip()]


def roots(start, seen=None):
    seen = set() if seen is None else seen
    if start in seen:
        return []
    seen.add(start)
    result = [start]
    for path in json.loads((start / 'run-manifest.json').read_text())['config'].get('resume_roots', []):
        result += roots(REPO / path, seen)
    return result


def cases():
    manifest = json.loads((REPO / 'docs/baselines/b0/datasets-v1.json').read_text())['dulemon_gold']
    source = REPO / manifest['path']; assert sha(source) == manifest['sha256']
    data = {r['conversation_id']: r for r in read_lines(source)}
    result = []
    for row in read_lines(RUN / 'imports-private.jsonl'):
        if row['dataset'] != 'dulemon_gold' or row['mode'] != 'full':
            continue
        path = Path('mappings') / (digest(['dulemon_gold', row['conversation_id'], 'full', row['repeat']]) + '.json')
        files = [r / path for r in roots(RUN) if (r / path).exists()]
        assert files
        mapping = json.loads(files[0].read_text()); assert len(mapping) == row['memories']
        conv = data[row['conversation_id']]
        result.append({'id': digest([row['conversation_id'], row['repeat']]),
            'conversation_id': row['conversation_id'], 'repeat': row['repeat'],
            'conversation': conv['documents'], 'gold': conv['metadata']['gold_memory_points'],
            'candidates': [{'id': 'p' + str(i), 'content': m['text']} for i, m in enumerate(mapping)],
            'mapping_sha256': sha(files[0]), 'source_sha256': manifest['sha256']})
    return result


def validate(value, case):
    assert set(value) == {'candidates', 'covered_gold_ids'}
    expected = {r['id'] for r in case['candidates']}
    gold = {r['item_id'] for r in case['gold']}
    assert len(value['candidates']) == len(expected)
    assert {r['id'] for r in value['candidates']} == expected
    union = set()
    for row in value['candidates']:
        assert set(row) == {'id', 'correct', 'wrong_subject', 'gold_ids', 'reason_code'}
        assert type(row['correct']) is bool and type(row['wrong_subject']) is bool
        assert not (row['correct'] and row['wrong_subject'])
        assert set(row['gold_ids']) <= gold
        assert row['reason_code'] in {'MATCH', 'UNSUPPORTED', 'TRANSIENT', 'WRONG_SUBJECT', 'PARTIAL'}
        union.update(row['gold_ids'])
    assert set(value['covered_gold_ids']) == union
    return value


async def main():
    global ROOT
    parser = argparse.ArgumentParser(); parser.add_argument('--round', type=int, choices=[1, 2], default=1)
    args = parser.parse_args()
    if args.round == 2:
        ROOT = ROOT.with_name('extraction-v2')
    ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    items = cases()
    prompt_path = REPO / f'docs/evals/prompts/extraction-assessment-v{args.round}.txt'
    prompt = prompt_path.read_text()
    _, base, key = credential('tokenhub-secondary')
    checkpoint = ROOT / 'assessments-private.json'
    done = json.loads(checkpoint.read_text()) if checkpoint.exists() else []
    sem = asyncio.Semaphore(3)
    print(json.dumps({'planned_conversation_repeat_cases': len(items), 'max_new_model_calls': len(items)*2,
        'candidate_outputs': sum(len(c['candidates']) for c in items), 'gold_repeated': sum(len(c['gold']) for c in items),
        'prompt_sha256': sha(prompt_path), 'human_calibration': 'required for new semantic task; original QA300 does not transfer automatically'}), flush=True)
    async with httpx.AsyncClient(trust_env=False, timeout=120) as client:
        async def one(case, model):
            if any(r['case_id'] == case['id'] and r['model'] == model for r in done):
                return
            async with sem:
                body = {'model': model, 'temperature': 0, 'thinking': {'type': 'disabled'},
                    'max_tokens': 2048, 'response_format': {'type': 'json_object'},
                    'messages': [{'role': 'system', 'content': prompt}, {'role': 'user', 'content': json.dumps(
                        {k: case[k] for k in ('conversation', 'gold', 'candidates')}, ensure_ascii=False)}]}
                if not case['candidates']:
                    value = {'candidates': [], 'covered_gold_ids': []}
                    record = {'case_id': case['id'], 'model': model, 'value': value, 'deterministic_empty': True}
                else:
                    f = ROOT / f'{case["id"]}-{model}-request-private.json'
                    f.write_text(json.dumps(body, ensure_ascii=False) + '\n'); f.chmod(0o600)
                    response = await client.post(base + '/chat/completions', headers={'Authorization': 'Bearer ' + key}, json=body)
                    data = response.json(); f = ROOT / f'{case["id"]}-{model}-response-private.json'
                    f.write_text(json.dumps(data, ensure_ascii=False) + '\n'); f.chmod(0o600)
                    value = None
                    try:
                        if response.status_code == 200 and data.get('model') == model:
                            value = validate(json.loads(data['choices'][0]['message']['content']), case)
                    except (ValueError, KeyError, AssertionError, TypeError):
                        pass
                    record = {'case_id': case['id'], 'model': model, 'value': value,
                        'http': response.status_code, 'usage': data.get('usage'), 'response_model': data.get('model')}
                done.append(record)
                checkpoint.write_text(json.dumps(done, ensure_ascii=False) + '\n'); checkpoint.chmod(0o600)
        await asyncio.gather(*(one(case, model) for case in items for model in ('glm-5.2', 'minimax-m3')))
    by_model = {}
    for model in ('glm-5.2', 'minimax-m3'):
        groups = defaultdict(lambda: [0, 0, 0, 0, 0])
        invalid = 0
        for case in items:
            answer = next(r for r in done if r['case_id'] == case['id'] and r['model'] == model)
            if answer['value'] is None:
                invalid += 1; continue
            value = answer['value']; g = groups[case['conversation_id']]
            g[0] += sum(r['correct'] for r in value['candidates']); g[1] += len(case['candidates'])
            g[2] += len(value['covered_gold_ids']); g[3] += len(case['gold'])
            g[4] += sum(r['wrong_subject'] for r in value['candidates'])
        precision = ratio([(v[0], v[1]) for v in groups.values()]).to_dict()
        recall = ratio([(v[2], v[3]) for v in groups.values()]).to_dict()
        p, r = precision['value'], recall['value']
        by_model[model] = {'EX1': precision, 'EX2': recall,
            'EX3': None if p is None or r is None else (2*p*r/(p+r) if p+r else 0.0),
            'EX5': ratio([(v[4], v[1]) for v in groups.values()]).to_dict(), 'invalid_cases': invalid,
            'formal': False, 'reason': 'new extraction matching/validity task requires owner review; model-derived diagnostics only'}
    review = []
    for case in items:
        source = json.dumps({'conversation': case['conversation'], 'human_gold': case['gold']}, ensure_ascii=False)
        for candidate in case['candidates']:
            review.append({'item_id': 'ex-p-' + digest([case['id'], candidate['id']])[:20],
                'question': '该候选是否有原对话依据、有长期保存价值且归属正确？1是，0否。',
                'reference': source, 'answer': candidate['content'], 'human_correct': '', 'human_reason': ''})
        for gold in case['gold']:
            review.append({'item_id': 'ex-r-' + digest([case['id'], gold['item_id']])[:20],
                'question': '候选中是否完整保留了该人工金标准的意思及归属？1是，0否。',
                'reference': json.dumps(gold, ensure_ascii=False), 'answer': json.dumps(case['candidates'], ensure_ascii=False),
                'human_correct': '', 'human_reason': ''})
    with (ROOT / 'extraction-owner-review-private.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=['item_id', 'question', 'reference', 'answer', 'human_correct', 'human_reason'])
        writer.writeheader(); writer.writerows(review)
    (ROOT / 'extraction-owner-review-private.csv').chmod(0o600)
    (ROOT / 'cases-private.json').write_text(json.dumps(items, ensure_ascii=False) + '\n'); (ROOT / 'cases-private.json').chmod(0o600)
    report = {'dataset': 'frozen selected DuLeMon dev8 conversations, full pipeline three repeats',
        'memory_outputs': sum(len(c['candidates']) for c in items), 'human_gold_repeated': sum(len(c['gold']) for c in items),
        'prompt_sha256': sha(prompt_path), 'prompt_version': args.round, 'models': by_model, 'owner_review_rows': len(review),
        'owner_review_sha256': sha(ROOT / 'extraction-owner-review-private.csv'),
        'model_comparison_independent': 'different vendors GLM/MiniMax, same frozen inputs; agreement is not human calibration',
        'human_semantic_calibration_complete': False, 'phase2_accepted': False,
        'limitation': 'Original QA300 calibrates question answering, not this new extraction task. No exact-string heuristic substituted for semantic precision/recall. Empty-candidate cases are deterministic recall misses, not model failures. Human data only server private.'}
    out = REPO / 'docs/reports/phase2-b0-completion-2026-10-28'; out.mkdir(parents=True, exist_ok=True)
    (out / f'extraction-diagnostic-v{args.round}.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    asyncio.run(main())
