"""Five real judge-prompt controls after the new account's full format preflight."""
import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx

from agent_memory.evals.evidence_v3 import sha
from agent_memory.evals.judge_http import ProviderJudgeRouter
from agent_memory.evals.judge_pool import Judge, JudgeFailure


async def main():
    model, vendor = sys.argv[1:3]
    account = os.environ['AGENT_MEMORY_LLM_ACCOUNT']
    root = Path('.local/phase1/round3/new-accounts-v1')
    generic = root / 'judge-preflight' / account / (model + '-summary.json')
    repaired = root / 'judge-repair' / account / model / (model + '-summary.json')
    if repaired.exists():
        generic = repaired
    assert json.loads(generic.read_text())['preflight_pass'], 'full preflight required first'
    out = root / 'judge-controls' / account / (model + '.json')
    assert not out.exists(), 'do not overwrite historical judge controls'
    out.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    prompt = Path('docs/evals/prompts/judge-v1.txt')
    rows = []
    async with httpx.AsyncClient(timeout=90, trust_env=False) as client:
        router = ProviderJudgeRouter(client, prompt.read_text(), {
            'TokenHub': os.environ.get('TENCENT_API_KEY', ''),
            'Ark': os.environ.get('ARK_API_KEY', ''),
        }, os.environ.get('TENCENT_BASE_URL', 'https://tokenhub.tencentmaas.com/v1'))
        provider = 'Ark' if account == 'ark-secondary' else 'TokenHub'
        for number in range(5):
            await asyncio.sleep(3.1)
            try:
                grade = await router(Judge(model, vendor, True, provider=provider), {
                    'row_id': str(number), 'question': '虚构人物偏好什么饮品？',
                    'reference': '红茶', 'answer': '红茶',
                })
                rows.append({'valid': True, 'score': grade.score, 'version': grade.response_model, 'usage': grade.usage})
            except JudgeFailure as error:
                rows.append({'valid': False, 'http_status': error.status})
                break
            out.write_text(json.dumps({'model': model, 'account': account, 'calls': rows, 'complete': False}, indent=2))
    result = {
        'model': model, 'vendor': vendor, 'provider': provider, 'account': account,
        'at': datetime.now(UTC).isoformat(), 'fictional_only': True, 'human_calibrated': False,
        'prompt_sha256': sha(prompt), 'generic_preflight_sha256': sha(generic),
        'calls': rows, 'complete': True,
        'passed': len(rows) == 5 and all(r.get('valid') for r in rows) and len({r.get('score') for r in rows}) == 1,
    }
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(result))


if __name__ == '__main__':
    os.umask(0o077)
    asyncio.run(main())
