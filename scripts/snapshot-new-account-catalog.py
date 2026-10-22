"""Save catalog metadata only; catalog presence is not successful-call evidence."""
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import httpx


def main():
    account = os.environ['AGENT_MEMORY_LLM_ACCOUNT']
    ark = account == 'ark-secondary'
    base = 'https://ark.cn-beijing.volces.com/api/v3' if ark else os.environ['TENCENT_BASE_URL'].rstrip('/')
    key = os.environ['ARK_API_KEY' if ark else 'TENCENT_API_KEY']
    response = httpx.get(base + '/models', headers={'Authorization': 'Bearer ' + key}, timeout=30, trust_env=False)
    data = response.json()
    result = {
        'account': account, 'queried_at': datetime.now(UTC).isoformat(), 'http': response.status_code,
        'models': [{k: row.get(k) for k in ('id', 'name', 'status', 'owned_by')} for row in data.get('data', [])],
        'not_a_quota_or_permission_claim': True,
    }
    path = Path('.local/phase1/round3/new-accounts-v1') / (account + '-catalog.json')
    assert not path.exists(), 'immutable catalog snapshot'
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'account': account, 'http': response.status_code, 'models': len(result['models'])}))


if __name__ == '__main__':
    os.umask(0o077)
    main()
