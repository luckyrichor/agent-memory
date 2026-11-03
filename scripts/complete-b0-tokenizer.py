"""Frozen DeepSeek real tokenizer sidecar, verified against actual same-model API usage."""
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path

import httpx
from tokenizers import Tokenizer

from agent_memory.evals.metrics import ratio

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'scripts'))
from b0_accounts import credential


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    root = REPO / '.local/phase2/b0/completion-20261028/tokenizer'
    source = REPO / '.local/phase2/b0/frozen-deepseek-20261026-v1/recovery-run-2/results-private.jsonl'
    rows = [json.loads(s) for s in source.read_text().splitlines() if s.strip()]
    rows = [r for r in rows if r['system'] == 'system' and r['system_context'] is not None]
    tokenizer = Tokenizer.from_file(str(root / 'tokenizer.json'))
    records = []
    for row in rows:
        assert isinstance(row['context'], str)
        records.append({'row_id': row['row_id'], 'dataset': row['dataset'], 'mode': row['mode'],
            'conversation_id': row['conversation_id'], 'repeat': row['repeat'],
            'context_sha256': hashlib.sha256(row['context'].encode()).hexdigest(),
            'estimated_byte_units': row['system_context']['used_tokens'],
            'budget': row['system_context']['budget'],
            'actual_official_tokenizer_tokens': len(tokenizer.encode(row['context'], add_special_tokens=False).ids)})
    groups = defaultdict(list)
    for record in records:
        groups[record['dataset'], record['mode']].append(record)
    values = {}
    for key, items in groups.items():
        clusters = defaultdict(list)
        for item in items:
            clusters[item['conversation_id']].append(item)
        values['/'.join(key)] = {
            'CX1': ratio([(sum(x['actual_official_tokenizer_tokens'] for x in c), sum(x['budget'] for x in c)) for c in clusters.values()]).to_dict(),
            'CX2_signed_estimate_minus_true_per_true': ratio([(sum(x['estimated_byte_units'] - x['actual_official_tokenizer_tokens'] for x in c), sum(x['actual_official_tokenizer_tokens'] for x in c)) for c in clusters.values()]).to_dict(),
            'CX2_absolute_error_per_true': ratio([(sum(abs(x['estimated_byte_units'] - x['actual_official_tokenizer_tokens']) for x in c), sum(x['actual_official_tokenizer_tokens'] for x in c)) for c in clusters.values()]).to_dict(),
            'rows': len(items), 'method': 'frozen rendered context only, official tokenizer add_special_tokens=False; conversation-cluster bootstrap, no API question/chat framing or counter change'}
    _, base, key = credential('deepseek-direct')
    candidates = [r for r in sorted(rows, key=lambda r: r['row_id']) if r['context']]
    # Fixed deterministic coverage: one nonempty English/Chinese context per observed dataset.
    chosen = []
    for dataset in sorted({r['dataset'] for r in candidates}):
        chosen.append(next(r['context'] for r in candidates if r['dataset'] == dataset))
    texts = ['', '完全虚构的分词计数对照。', 'A fictional tokenizer cross-check.'] + chosen
    probes = []
    with httpx.Client(trust_env=False, timeout=90) as client:
        for i, content in enumerate(texts):
            body = {'model': 'deepseek-v4-pro', 'temperature': 0, 'thinking': {'type': 'disabled'},
                'max_tokens': 1, 'messages': [{'role': 'user', 'content': content}]}
            response = client.post(base + '/chat/completions', headers={'Authorization': 'Bearer ' + key}, json=body)
            data = response.json()
            for name, value in [('request', body), ('response', data)]:
                f = root / f'crosscheck-{i}-{name}-private.json'
                f.write_text(json.dumps(value, ensure_ascii=False) + '\n'); f.chmod(0o600)
            if response.status_code != 200 or data.get('model') != 'deepseek-v4-pro':
                raise RuntimeError('FIXED_MODEL_TOKENIZER_CHECK_UNAVAILABLE')
            probes.append({'index': i, 'content_sha256': hashlib.sha256(content.encode()).hexdigest(),
                'official_text_tokens': len(tokenizer.encode(content, add_special_tokens=False).ids),
                'api_prompt_tokens': data['usage']['prompt_tokens'], 'usage': data['usage']})
    overhead = probes[0]['api_prompt_tokens']
    for probe in probes:
        probe['api_delta_without_empty_chat_overhead'] = probe['api_prompt_tokens'] - overhead
        probe['local_minus_api_delta'] = probe['official_text_tokens'] - probe['api_delta_without_empty_chat_overhead']
    metadata = json.loads((root / 'hf-metadata.json').read_text())
    report = {'model': 'deepseek-v4-pro', 'official_repository': 'deepseek-ai/DeepSeek-V4-Pro',
        'revision': metadata['sha'], 'tokenizer_sha256': sha(root / 'tokenizer.json'),
        'tokenizer_config_sha256': sha(root / 'tokenizer_config.json'), 'tokenizers_package': '0.22.2',
        'source_results_sha256': sha(source), 'rows': len(records), 'by_dataset_mode': values,
        'api_crosscheck': probes, 'api_calls': len(probes),
        'api_token_differences': [p['local_minus_api_delta'] for p in probes],
        'source_urls': ['https://huggingface.co/deepseek-ai/DeepSeek-V4-Pro', 'https://api-docs.deepseek.com/quick_start/token_usage/'],
        'limit': 'Official released same-model tokenizer, sample-checked against live API. API usage remains authority for billing; hidden tokenizer/version drift outside sampled texts unverified. Empty context has zero text tokens, so CX2 zero denominator stays null. B0 UTF8 counter/budget unchanged.',
        'phase2_accepted': False}
    private = root / 'records-private.json'; private.write_text(json.dumps(records) + '\n'); private.chmod(0o600)
    out = REPO / 'docs/reports/phase2-b0-completion-2026-10-28'
    out.mkdir(parents=True, exist_ok=True)
    (out / 'tokenizer.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'rows': len(records), 'calls': len(probes), 'differences': report['api_token_differences'], 'groups': len(values)}), flush=True)


if __name__ == '__main__':
    main()
