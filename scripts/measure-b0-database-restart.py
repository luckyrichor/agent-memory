"""Write through the frozen HTTP API while restarting only the isolated database."""
import asyncio
from collections import Counter
import json
from pathlib import Path
import time
from uuid import uuid4

import httpx
import jwt
import psycopg

ROOT = Path(__file__).resolve().parents[1]
CAP = ROOT/'.local/phase2/b0/completion-20261028/capacity'


async def main():
    cfg = json.loads((CAP/'fault-config-private.json').read_text())
    with psycopg.connect(cfg['root_dsn']) as c:
        tenant,owner,content = c.execute('SELECT m.tenant_id,m.owner_user_id,v.content FROM memories m JOIN memory_versions v ON v.tenant_id=m.tenant_id AND v.memory_version_id=m.current_version_id ORDER BY m.memory_id LIMIT 1').fetchone()
    now = int(time.time())
    token = jwt.encode({'iss':'b0-capacity','aud':'b0-capacity','iat':now,'exp':now+3600,
                        'tenant_id':str(tenant),'sub':str(owner),'permissions':['memory:read','memory:write'],
                        'allowed_workspace_ids':['pf']},(CAP/'jwt-private.pem').read_text(),algorithm='RS256')
    body = {'content':content,'memory_type':'episodic','scope':{'kind':'workspace','workspace_id':'pf'}}
    observations = []; all_confirmed = []
    async with httpx.AsyncClient(verify=False,trust_env=False,timeout=10) as client:
        for repeat in range(3):
            statuses = Counter(); confirmed = []; stop = False; started = time.monotonic()
            async def writer():
                while not stop:
                    try:
                        r = await client.post('https://127.0.0.1:18443/v1/memories',json=body,
                            headers={'Authorization':'Bearer '+token,'Idempotency-Key':str(uuid4())})
                        statuses[str(r.status_code)] += 1
                        if r.status_code == 201: confirmed.append(r.json()['memory_id'])
                    except httpx.TransportError:
                        statuses['transport_error'] += 1
                    await asyncio.sleep(.05)
            task = asyncio.create_task(writer())
            await asyncio.sleep(2)
            assert confirmed, 'API_SUCCESSFUL_WRITE_PREFLIGHT_REQUIRED'
            before = len(confirmed); restart_at = time.monotonic()
            restart = await asyncio.create_subprocess_exec('docker','restart','--time','1','agent-memory-b0-capacity-20261028',
                stdout=asyncio.subprocess.DEVNULL,stderr=asyncio.subprocess.DEVNULL)
            assert await restart.wait() == 0
            deadline = time.monotonic()+60
            while len(confirmed) < before+10 and time.monotonic()<deadline:
                await asyncio.sleep(.2)
            stop = True; await task
            assert len(confirmed) >= before+10, 'API_DID_NOT_RECOVER'
            with psycopg.connect(cfg['root_dsn']) as c:
                actual = c.execute('SELECT count(*) FROM memories WHERE memory_id=ANY(%s::uuid[])',(confirmed,)).fetchone()[0]
            item = {'repeat':repeat+1,'confirmed_writes':len(confirmed),'confirmed_present':actual,
                    'confirmed_missing':len(confirmed)-actual,'status_counts':dict(statuses),
                    'restart_to_ten_more_successful_writes_seconds':time.monotonic()-restart_at,
                    'total_seconds':time.monotonic()-started}
            observations.append(item);all_confirmed.extend(confirmed);print(json.dumps(item),flush=True)
            assert actual == len(confirmed)
    (CAP/'restart-confirmed-ids-private.json').write_text(json.dumps(all_confirmed)+'\n')
    report = {'scenario':'F1_partial','observations':observations,'confirmed_write_loss':sum(r['confirmed_missing'] for r in observations),
              'limitation':'Actual API writes during three Docker database restarts and acknowledged-row verification. Recovery is ten additional successful writes, not p95 returning to baseline; explicit retryable error semantics must be assessed from actual status counts. Performance acceptance not inferred.',
              'external_model_calls':0}
    (ROOT/'docs/reports/phase2-b0-completion-2026-10-28/database-restart.json').write_text(json.dumps(report,indent=2)+'\n')


if __name__ == '__main__':
    asyncio.run(main())
