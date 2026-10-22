"""Resume saved new-key fictional preflight responses without repeating completed calls."""
import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import httpx

from agent_memory.evals import model_preflight as preflight
from agent_memory.evals.evidence_v3 import sha
from agent_memory.evals.metrics import latency

ROOT = Path('.local/phase1/round3/new-accounts-v1/judge-preflight/tokenhub-secondary')
PROMPT = Path('docs/evals/prompts/preflight-v1.txt')


async def main():
    assert os.environ['AGENT_MEMORY_LLM_ACCOUNT'] == 'tokenhub-secondary'
    records = json.loads((ROOT/'progress.json').read_text())
    raw = json.loads((ROOT/'raw-local-only.json').read_text())
    assert len(records) == len(raw)
    async with httpx.AsyncClient(timeout=60, trust_env=False) as client:
        for model in ('glm-5.2', 'mimo-v2.6-flash', 'minimax-m3'):
            existing = [r for r in records if r['model'] == model]
            if (ROOT/(model+'-summary.json')).exists():
                continue
            for number in range(len(existing), 106):
                if existing and (existing[-1].get('http_status') in (400,401,402,403,404) or existing[-1].get('observed_disabled_thinking') is False):
                    break
                await asyncio.sleep(3.1)
                attempts = []
                for attempt in range(5):
                    record, response = await preflight.probe(client, model, PROMPT.read_text(), number, repeated=number<6)
                    attempts.append({k:v for k,v in record.items() if k!='label'})
                    if record.get('http_status') != 429:
                        break
                    await asyncio.sleep(min(60,5*2**attempt))
                record['attempts'] = attempts
                records.append(record)
                existing.append(record)
                raw.append(response)
                (ROOT/'progress.json').write_text(json.dumps(records,indent=2))
                (ROOT/'raw-local-only.json').write_text(json.dumps(raw,ensure_ascii=False))
                if number % 25 == 0:
                    print(json.dumps({'model':model,'completed':number+1}),flush=True)
            repeated = existing[1:6]
            formatted = existing[6:]
            valid = sum(bool(r.get('format_valid')) for r in formatted)
            consistent = len(repeated)==5 and all(r.get('format_valid') for r in repeated) and len({r.get('label') for r in repeated})==1
            summary = {
                'model':model,'account':'tokenhub-secondary','at':datetime.now(UTC).isoformat(),
                'calls':len(existing),'format_valid':valid,'format_n':len(formatted),
                'consistent_5':consistent,'observed_disabled_thinking':all(r.get('observed_disabled_thinking') for r in existing),
                'preflight_pass':len(formatted)==100 and valid>=99 and consistent and bool(existing[0].get('format_valid')) and all(r.get('observed_disabled_thinking') for r in existing),
                'latency_ms':latency([r['latency_ms'] for r in existing]),
                'http_429':sum(a.get('http_status')==429 for r in existing for a in r['attempts']),
                'resumed_saved_responses_not_reissued':True,
            }
            (ROOT/(model+'-summary.json')).write_text(json.dumps(summary,indent=2)+'\n')
            print(json.dumps(summary),flush=True)
    (ROOT/'report.json').write_text(json.dumps({'created_at':datetime.now(UTC).isoformat(),'account':'tokenhub-secondary','prompt_sha256':sha(PROMPT),'parameters':{'temperature':0,'thinking':'disabled','max_tokens':256,'format_samples':100},'scope':'fictional format controls, NOT human judge calibration','records':records},indent=2)+'\n')


if __name__ == '__main__':
    os.umask(0o077)
    asyncio.run(main())
