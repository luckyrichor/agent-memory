"""Retry only unanswered transport failures; never retry an invalid model answer to pass."""
import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import httpx

from agent_memory.evals import model_preflight as preflight
from agent_memory.evals.evidence_v3 import sha
from agent_memory.evals.metrics import latency


async def main():
    assert os.environ['AGENT_MEMORY_LLM_ACCOUNT']=='tokenhub-secondary'
    root=Path('.local/phase1/round3/new-accounts-v1')
    source=root/'judge-preflight/tokenhub-secondary/progress.json'
    rows=[r for r in json.loads(source.read_text()) if r['model']=='mimo-v2.6-flash']
    assert len(rows)==106
    failed=[r for r in rows if not r.get('format_valid') or not r.get('observed_disabled_thinking')]
    assert failed and all(r.get('http_status') is None and r.get('error_type') in ('RemoteProtocolError','ReadTimeout','ConnectTimeout','ConnectError') for r in failed), 'only no-response transport failures may be repaired'
    out=root/'judge-repair/tokenhub-secondary/mimo-v2.6-flash'
    out.mkdir(parents=True,exist_ok=False,mode=0o700)
    prompt=Path('docs/evals/prompts/preflight-v1.txt')
    calls=[]
    async with httpx.AsyncClient(timeout=60,trust_env=False) as client:
        for original in failed:
            for attempt in range(3):
                await asyncio.sleep(3.1)
                record, raw=await preflight.probe(client,original['model'],prompt.read_text(),original['number'],repeated=original['repeated'])
                calls.append(record)
                (out/f"{original['number']:03d}-{attempt}-raw-private.json").write_text(json.dumps(raw,ensure_ascii=False))
                (out/'new-attempts.json').write_text(json.dumps(calls,indent=2)+'\n')
                if record.get('http_status') is not None:
                    break
            rows[rows.index(original)]=record
    repeated=rows[1:6];formatted=rows[6:]
    summary={
        'model':'mimo-v2.6-flash','account':'tokenhub-secondary','at':datetime.now(UTC).isoformat(),
        'calls':len(rows),'new_calls':len(calls),'format_valid':sum(bool(r.get('format_valid')) for r in formatted),
        'format_n':len(formatted),'consistent_5':len(repeated)==5 and all(r.get('format_valid') for r in repeated) and len({r.get('label') for r in repeated})==1,
        'observed_disabled_thinking':all(r.get('observed_disabled_thinking') for r in rows),
        'same_100_inputs_no_replacement':True,'original_failed_requests':len(failed),
        'prompt_sha256':sha(prompt),'source_progress_sha256':sha(source),
        'latency_ms':latency([r['latency_ms'] for r in rows]),
        'scope':'bounded retries only for unanswered transport failures, not answer/format resampling',
    }
    summary['preflight_pass']=summary['format_n']==100 and summary['format_valid']>=99 and summary['consistent_5'] and summary['observed_disabled_thinking']
    (out/'resolved-rows-private.json').write_text(json.dumps(rows,indent=2)+'\n')
    (out/'mimo-v2.6-flash-summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary))


if __name__=='__main__':
    os.umask(0o077)
    asyncio.run(main())
