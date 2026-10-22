"""Frozen dev/final experiment, then conditional full DuLeMon relabel. Private artifacts only."""
import argparse
import asyncio
import hashlib
import json
import os
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

from agent_memory.evals.annotate import shared_sources
from agent_memory.evals.approved_audit import prepare_joint_audit
from agent_memory.evals.evidence_v3 import (
    MODELS, VERSION, EvidenceBatch, gate, grouped_split, metrics, read_rows, sha, validate_quotes,
)
from agent_memory.evals.model_policy import require_disabled_thinking

ROOT = Path('.local/phase1/round3/evidence-v3')
ITEMS = Path('.local/phase1/chinese-expansion-v2/dulemon/items.jsonl')
HUMAN = Path('.local/phase1/round3/verbatim-filter/run-final/human-confirmed-labels.jsonl')
MAP = Path('.local/phase1/round3/approved-followup/joint-audit-72-v1/opaque-map-private.json')
PROMPT = Path('docs/evals/prompts/labeling-guide-v3-evidence-v1.txt')
MODULE = Path('src/agent_memory/evals/evidence_v3.py')
SCRIPT = Path(__file__)


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def lines(path, rows):
    path.write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows))


def inputs():
    items = {r['item_id']: r for r in read_rows(ITEMS)}
    human = {r['item_id']: r for r in read_rows(HUMAN)}
    new = set(json.loads(MAP.read_text()).values())
    groups = {k: ('blind72-' if k in new else 'native157-') + v['label'] for k, v in human.items()}
    assert len(human) == 229 and len(new) == 72 and len(items) == 2291
    assert Counter(groups.values()) == {'blind72-keep': 63, 'blind72-discard': 9,
                                        'native157-keep': 22, 'native157-discard': 135}
    return items, human, groups


def prepare():
    items, _, groups = inputs()
    manifest = ROOT / 'manifest.json'
    if manifest.exists():
        raise ValueError('experiment already frozen; do not redraw or overwrite')
    split = grouped_split(items, groups)
    write(ROOT / 'split-private.json', split)
    for stage in ('development', 'final'):
        lines(ROOT / (stage + '-items.jsonl'), [items[k] for k in split[stage]])
    files = [ITEMS, HUMAN, MAP, PROMPT, MODULE, SCRIPT, ROOT / 'split-private.json',
             ROOT / 'development-items.jsonl', ROOT / 'final-items.jsonl']
    frozen = {
        'version': VERSION, 'models': list(MODELS), 'provider': 'TokenHub',
        'created_beijing': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
        'split_seed': split['seed'], 'new_blind_sample_seed': 20261023,
        'files': {str(p): sha(p) for p in files},
        'prompt_variants_allowed_this_run': 1, 'final_evaluation_runs_allowed': 1,
        'development_counts': split['development_strata'], 'final_counts': split['final_strata'],
        'conversation_overlap': split['conversation_overlap'],
        'historical_exposure': split['historical_exposure'],
        'thresholds': {'known_error_block': 8/9, 'blind_correct_retention': .6,
                       'native_correct_retention': .6, 'next_audit_max_errors': 3},
        'gate_scope': 'joint validated keep; development AND final AND aggregate separately pass; final small-error stratum requires ceil(8/9*n) blocked',
        'human_current_positive': 85, 'minimum': 700, 'target': 1500,
        'authorization': 'om_x100b62a18b11e0acb09f793d77af4fa',
        'full_relabel': 'only after complete offline validation passes; same models, new complete batch',
    }
    write(manifest, frozen)
    print(json.dumps({k: frozen[k] for k in ('development_counts', 'final_counts', 'conversation_overlap')}))


def verify():
    frozen = json.loads((ROOT / 'manifest.json').read_text())
    assert frozen['models'] == list(MODELS)
    for p, expected in frozen['files'].items():
        if sha(Path(p)) != expected:
            raise ValueError('frozen experiment input or prompt/source changed: ' + p)
    return frozen


async def run_model(stage, model, rows):
    directory = ROOT / stage / model
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    ledger_path = directory / 'ledger.json'
    ledger = json.loads(ledger_path.read_text()) if ledger_path.exists() else []
    if ledger and ledger[-1]['status'] != 'complete':
        return False  # no silent rerun of failure, no holdout retuning
    by_batch = {r['offset']: r for r in ledger}
    token = os.environ.get('TOKENHUB_API_KEY') or os.environ.get('TENCENT_API_KEY')
    if not token:
        raise ValueError('use authorized with-tencent wrapper')
    base = os.environ.get('TENCENT_BASE_URL', 'https://tokenhub.tencentmaas.com/v1').rstrip('/')
    async with httpx.AsyncClient(timeout=150, trust_env=False) as client:
        for offset in range(0, len(rows), 4):
            batch = rows[offset:offset+4]
            if offset in by_batch:
                continue
            aliases = {f'i{j}': row for j, row in enumerate(batch)}
            wire = [{**row, 'item_id': alias} for alias, row in aliases.items()]
            # Only allowed five source fields; no human answers, categories or prior labels.
            assert all(set(r) == {'item_id', 'conversation_id', 'subject', 'source', 'candidate'} for r in wire)
            body = {
                'model': model, 'temperature': 0, 'max_tokens': 8192,
                'thinking': {'type': 'disabled'}, 'response_format': {'type': 'json_object'},
                'messages': [{'role': 'system', 'content': PROMPT.read_text()},
                             {'role': 'user', 'content': json.dumps(shared_sources(wire), ensure_ascii=False)}],
            }
            entry = {'offset': offset, 'items': len(batch), 'status': 'started',
                     'requested_model': model, 'provider': 'TokenHub', 'stage': stage,
                     'prompt_sha256': sha(PROMPT), 'timestamp': datetime.now().astimezone().isoformat(),
                     'request_sha256': hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()}
            ledger.append(entry)
            write(ledger_path, ledger)
            write(directory / f'{offset:04d}-request.json', body)
            try:
                response = await client.post(base + '/chat/completions', json=body,
                                             headers={'Authorization': 'Bearer ' + token})
                entry['http_status'] = response.status_code
                # Restricted raw body only, never headers/tokens or terminal output.
                (directory / f'{offset:04d}-response.json').write_text(response.text)
                if not response.is_success:
                    entry['status'] = 'http-failed'
                    write(ledger_path, ledger)
                    print(json.dumps({'stage': stage, 'model': model, 'http': response.status_code}))
                    return False
                data = response.json()
                entry['usage'] = data.get('usage')
                entry['returned_model'] = data.get('model')
                require_disabled_thinking(data)
                if data['choices'][0].get('finish_reason') not in ('stop', None):
                    raise ValueError('truncated model answer')
                parsed = EvidenceBatch.model_validate_json(data['choices'][0]['message']['content'])
                if len(parsed.labels) != len(aliases) or {r.item_id for r in parsed.labels} != set(aliases):
                    raise ValueError('response ID coverage invalid')
                checked = []
                proofs = []
                for label in parsed.labels:
                    item = aliases[label.item_id]
                    original = label.model_copy(update={'item_id': item['item_id']})
                    checked.append(validate_quotes(original, item))
                    proofs.append(original.model_dump())
                lines(directory / f'{offset:04d}-checked.jsonl', checked)
                lines(directory / f'{offset:04d}-proofs.jsonl', proofs)
                entry['status'] = 'complete'
            except Exception as exc:
                entry.update(status='failed', error_type=type(exc).__name__)
                write(ledger_path, ledger)
                print(json.dumps({'stage': stage, 'model': model, 'error_type': type(exc).__name__}))
                return False
            write(ledger_path, ledger)
            print(json.dumps({'stage': stage, 'model': model, 'completed': offset+len(batch), 'total': len(rows)}), flush=True)
            await asyncio.sleep(1)
    predictions = [r for p in sorted(directory.glob('*-checked.jsonl')) for r in read_rows(p)]
    assert len(predictions) == len(rows)
    lines(directory / 'checked.jsonl', predictions)
    lines(directory / 'labels.jsonl', [{k: r[k] for k in ('item_id', 'label', 'reason')} for r in predictions])
    (directory / 'COMPLETE').write_text(sha(directory / 'checked.jsonl') + '\n')
    return True


def score(stage, groups, ids):
    per_model = {}
    predictions = {}
    complete = True
    for model in MODELS:
        path = ROOT / stage / model / 'checked.jsonl'
        complete &= (ROOT / stage / model / 'COMPLETE').exists()
        predictions[model] = {r['item_id']: r for r in read_rows(path)} if path.exists() else {}
        per_model[model] = metrics(predictions[model], groups, ids)
    overlap = predictions[MODELS[0]].keys() & predictions[MODELS[1]].keys()
    joint = {k: {'label': 'keep' if all(predictions[m][k]['label'] == 'keep' for m in MODELS)
                         else 'uncertain'} for k in overlap}
    joint_scores = metrics(joint, groups, ids)
    return {'complete': bool(complete), 'per_model': per_model, 'joint': joint_scores,
            'passed': bool(complete) and gate(joint_scores)}, joint


async def offline():
    verify()
    items, _, groups = inputs()
    split = json.loads((ROOT / 'split-private.json').read_text())
    for stage in ('development', 'final'):
        rows = [items[k] for k in split[stage]]
        completed = await asyncio.gather(*(run_model(stage, m, rows) for m in MODELS))
        if not all(completed):
            break
    report()


def report():
    frozen = verify()
    _, human, groups = inputs()
    split = json.loads((ROOT / 'split-private.json').read_text())
    dev, left = score('development', groups, split['development'])
    final, right = score('final', groups, split['final'])
    all_scores = metrics(left | right, groups, sorted(groups))
    accepted = dev['passed'] and final['passed'] and gate(all_scores)
    ledgers = [r for p in sorted(ROOT.glob('*/*/ledger.json')) for r in json.loads(p.read_text())]
    full_paths = [ROOT / 'full' / m / 'COMPLETE' for m in MODELS]
    result = {
        'version': VERSION, 'manifest_sha256': sha(ROOT / 'manifest.json'),
        'source_files': {str(p): sha(p) for p in (MODULE, SCRIPT, PROMPT)},
        'source_commit': os.popen('git rev-parse --short HEAD').read().strip(),
        'source_modified': bool(os.popen('git status --porcelain --untracked-files=no').read().strip()),
        'frozen': frozen, 'development': dev, 'final': final,
        'all_229_joint': all_scores, 'offline_passed': bool(accepted),
        'status': 'passed' if accepted else ('failed' if dev['complete'] and final['complete'] else 'incomplete'),
        'actual_calls': len(ledgers), 'http_counts': dict(Counter(str(x.get('http_status', 'unknown')) for x in ledgers)),
        'reported_total_tokens': sum((x.get('usage') or {}).get('total_tokens', 0) for x in ledgers),
        'usage_missing_calls': sum('usage' not in x for x in ledgers),
        'failures': [{k: x[k] for k in ('stage','requested_model','offset','status','http_status','error_type') if k in x}
                     for x in ledgers if x['status'] != 'complete'],
        'full_relabel_complete': all(p.exists() for p in full_paths),
        'new_audit_generated': (ROOT / 'fresh-audit72' / 'manifest.json').exists(),
        'human_positive_points': sum(x['label'] == 'keep' for x in human.values()),
        'gap_to_minimum': 700 - sum(x['label'] == 'keep' for x in human.values()),
        'phase1_accepted': False, 'incremental_annotation_started': False,
        'mechanical_checker_limitation': 'Only checks source identity, user role and exact quote substrings. Cannot prove semantic entailment, complete detail enumeration, or absence of negation/question/attribution errors inside a quote; models must judge these, then fresh human audit.',
    }
    write(ROOT / 'result.json', result)
    print(json.dumps({k: result[k] for k in ('status','offline_passed','actual_calls','http_counts','human_positive_points','gap_to_minimum')}))
    return result


async def full():
    result = report()
    if not result['offline_passed']:
        raise ValueError('offline gate not passed; full relabel prohibited')
    items, _, _ = inputs()
    completed = await asyncio.gather(*(run_model('full', m, list(items.values())) for m in MODELS))
    if all(completed):
        prepare_joint_audit(items=ITEMS, left=ROOT / 'full' / MODELS[0] / 'labels.jsonl',
                            right=ROOT / 'full' / MODELS[1] / 'labels.jsonl', prior_human=HUMAN,
                            output=ROOT / 'fresh-audit72', seed=20261023, sample_size=72)
    report()


if __name__ == '__main__':
    os.umask(0o077)
    p = argparse.ArgumentParser()
    p.add_argument('action', choices=['prepare', 'offline', 'report', 'full'])
    a = p.parse_args()
    if a.action == 'prepare': prepare()
    elif a.action == 'report': report()
    else: asyncio.run(offline() if a.action == 'offline' else full())
