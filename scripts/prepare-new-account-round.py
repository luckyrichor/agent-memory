"""Apply the owner's old-pool decision and freeze a fresh unused reserve order."""
import json
import math
import random
from pathlib import Path

from agent_memory.evals.evidence_v3 import read_rows, sha

BASE = Path('.local/phase1/round3/temporal-v1')
OUT = Path('.local/phase1/round3/new-accounts-v1')


def load(path):
    return json.loads(path.read_text())


def write(path, value):
    text = json.dumps(value, ensure_ascii=False, indent=2) + '\n'
    if path.exists():
        assert json.loads(path.read_text()) == value, 'frozen preparation changed'
    else:
        path.write_text(text)


def main():
    OUT.mkdir(exist_ok=True, mode=0o700)
    manifest = load(BASE / 'screen/manifest.json')
    pool = set(manifest['pool_ids'])
    rejected = set(manifest['new_human_rejected_ids'])
    positive = set(manifest['human_positive_ids'])
    adopted = pool - rejected
    union = adopted | positive
    items = {r['item_id']: r for r in read_rows(Path('.local/phase1/chinese-expansion-v2/dulemon/items.jsonl'))}
    for name, ids in [('adopted-old-pool', adopted), ('accepted-base-union', union)]:
        path = OUT / (name + '-private.jsonl')
        text = ''.join(json.dumps(items[k], ensure_ascii=False) + '\n' for k in sorted(ids))
        if path.exists():
            assert path.read_text() == text
        else:
            path.write_text(text)
    provenance = [
        {'item_id': k, 'label': 'keep',
         'labeling_method': 'owner-human-confirmed' if k in positive else 'owner-audit-approved-model-pool',
         'individually_human_confirmed': k in positive,
         'original_models': ['deepseek-v4.1-flash-1017','hy4-preview'] if k in adopted else [],
         'old_temporal_screen_applied': False}
        for k in sorted(union)
    ]
    write(OUT/'accepted-base-provenance-private.json', provenance)
    old_root = BASE / 'increment-batches-single-packet-v1'
    old = load(old_root / 'manifest.json')
    registry = load(old_root / 'batch-registry.json')
    selected = set()
    for record in registry:
        selected.update(load(Path(record['path']) / 'manifest.json')['new_indices'])
    failed = old_root / 'cohort-004-attempt-00/batch-004'
    redo_indices = load(failed / 'manifest.json')['new_indices']
    assert not selected & set(redo_indices)
    used = selected | set(redo_indices)
    remaining = sorted(set(old['available_indices']) - used)
    random.Random(20261029).shuffle(remaining)
    target = max(72, 700 - len(union) + 3)
    result = {
        'old_pool_original': len(pool), 'known_errors_removed': len(pool & rejected),
        'old_pool_adopted': len(adopted), 'old_pool_temporal_screen_applied': False,
        'human_confirmed': len(positive), 'overlap_human_old': len(adopted & positive),
        'old_pool_model_only': len(adopted - positive), 'base_reliable_union': len(union),
        'base_gap_700': max(0, 700-len(union)), 'base_gap_1500': max(0, 1500-len(union)),
        'completed_new_candidates': sum(r['candidates'] for r in registry),
        'completed_new_joint_keep': sum(r['joint_keep'] for r in registry),
        'target_new_joint_keep': target,
        'target_basis': 'owner-approved old union plus new joint keeps minus at most three final blind errors >=700; three is audit accounting, not a confidence guarantee',
        'new_joint_gap': max(0, target-sum(r['joint_keep'] for r in registry)),
        'completed_new_dialogues': len(selected), 'redo_dialogues': len(redo_indices),
        'unused_dialogues': len(remaining), 'supplement_seed': 20261029, 'audit_seed': 20261030,
        'phase1_accepted': False, 'new_pool_adopted': 0,
    }
    rate = result['completed_new_joint_keep'] / result['completed_new_candidates']
    candidates = math.ceil(result['new_joint_gap'] / rate)
    dialogues = math.ceil(candidates / (result['completed_new_candidates'] / result['completed_new_dialogues']))
    result['conditional_projection'] = {
        'basis': 'completed four batches only, observed yield; not achieved count',
        'joint_yield': rate, 'additional_candidates': candidates, 'additional_dialogues': dialogues,
        'two_side_packet8_calls': 2*math.ceil(candidates/8),
        'packet8_plus_packet1_calls': math.ceil(candidates/8)+candidates,
        'excludes_qualification_and_retries': True,
    }
    write(OUT / 'adoption-and-plan.json', result)
    reserve_path = OUT / 'new-reserve-indices-private.json'
    if reserve_path.exists():
        assert load(reserve_path) == remaining
    else:
        write(reserve_path, remaining)
    protected = OUT / 'ecd-unchanged-hashes.json'
    if protected.exists():
        for name, value in load(protected).items():
            assert sha(Path(name)) == value, 'ECD changed'
    else:
        write(protected, {str(p): sha(p) for p in [Path('docs/evals/ecd-human-current.json'), BASE/'ecd-owner/report.json', Path('.local/ecd120-human-labeled.csv')]})
    usage = {}
    for batch in registry:
        for ledger in Path(batch['path']).glob('shard-*/**/ledger.json'):
            for record in load(ledger):
                if record.get('cache_hit') or not record.get('usage'):
                    continue
                vendor = 'DeepSeek' if record['requested_model'].startswith('deepseek') else 'Tencent'
                u = usage.setdefault(vendor, {'calls': 0, 'items': 0, 'reported_tokens': 0})
                u['calls'] += len(record.get('attempts', []))
                u['items'] += record['items']
                u['reported_tokens'] += record['usage'].get('total_tokens', 0)
    for u in usage.values():
        u['mean_reported_tokens_per_item'] = u['reported_tokens'] / u['items']
    write(OUT/'token-projection.json', {
        'basis': 'old completed batches, actual responses only; conditional estimate, model/source lengths can change',
        'historical_means': usage, 'additional_candidate_estimate': candidates,
        'additional_token_estimate': math.ceil(candidates*sum(u['mean_reported_tokens_per_item'] for u in usage.values())),
        'retry_preflight_switch_tokens_excluded': True,
    })
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
