"""Same v3 parser and citation checks, TokenHub transport without unsupported JSON mode."""
import asyncio
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
import httpx
from agent_memory.evals.annotate import shared_sources
from agent_memory.evals.evidence_v3 import EvidenceBatch, read_rows, sha, validate_quotes
from agent_memory.evals.model_policy import require_disabled_thinking

ROOT = Path('.local/phase1/round3/tokenhub-pool')
PROMPT = Path('docs/evals/prompts/labeling-guide-v3-evidence-v3.txt')
BATCH_SIZE = 8
PROVIDERS = {k:'TokenHub' for k in ('deepseek-v4.1-flash-1017','deepseek-v4-flash-202605','deepseek/deepseek-flash','hy4-preview')}

def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')

def lines(path, rows):
    path.write_text(''.join(json.dumps(row, ensure_ascii=False)+'\n' for row in rows))

async def run_model(stage, model, rows):
    directory = ROOT / stage / model
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    ledger_path = directory / 'ledger.json'
    ledger = json.loads(ledger_path.read_text()) if ledger_path.exists() else []
    if ledger and ledger[-1]['status'] != 'complete':
        return False  # no silent rerun of failure, no holdout retuning
    by_batch = {r['offset']: r for r in ledger}
    provider = PROVIDERS[model]
    token = os.environ.get('ARK_API_KEY') if provider == 'Ark' else (os.environ.get('TOKENHUB_API_KEY') or os.environ.get('TENCENT_API_KEY'))
    if not token:
        raise ValueError('use authorized with-llm wrapper')
    base = 'https://ark.cn-beijing.volces.com/api/v3' if provider == 'Ark' else os.environ.get('TENCENT_BASE_URL', 'https://tokenhub.tencentmaas.com/v1').rstrip('/')
    async with httpx.AsyncClient(timeout=150, trust_env=False) as client:
        for offset in range(0, len(rows), BATCH_SIZE):
            batch = rows[offset:offset+BATCH_SIZE]
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
            if model != 'hy4-preview':
                body.pop('response_format')  # provider rejects this optional API mode
            entry = {'offset': offset, 'items': len(batch), 'status': 'started',
                     'requested_model': model, 'provider': provider, 'stage': stage,
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
