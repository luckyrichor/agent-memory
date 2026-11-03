"""Actual subprocess death and default lease recovery on an isolated synthetic clone."""
import asyncio
from datetime import datetime, timezone, timedelta
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from uuid import UUID

import psycopg

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('seed', ROOT/'scripts/prepare-b0-capacity-db.py')
seed = importlib.util.module_from_spec(spec); spec.loader.exec_module(seed)
CAP = seed.CAP
CONFIG = CAP/'fault-config-private.json'


async def child(tenant):
    config = json.loads(CONFIG.read_text())
    engine = seed.create_engine(config['database_url'])
    backend = seed.PostgresEmbeddingBackend(seed.create_session_factory(engine))
    job = await backend.claim(UUID(tenant), 'crashing-process', datetime.now(timezone.utc), timedelta(seconds=30))
    if not job:
        os._exit(78)
    print(str(job.job_id), flush=True)
    os._exit(77)  # Actual process dies while owning the lease; no graceful rollback of claim.


async def main():
    config = json.loads(CONFIG.read_text())
    engine = seed.create_engine(config['database_url'])
    backend = seed.PostgresEmbeddingBackend(seed.create_session_factory(engine))
    provider = seed.Precomputed(); worker = seed.EmbeddingWorker(backend, provider)
    results = []
    try:
        for repeat in range(3):
            with psycopg.connect(config['root_dsn']) as c:
                tenant, version = c.execute('SELECT tenant_id,memory_version_id FROM memory_versions ORDER BY memory_version_id LIMIT 1').fetchone()
            await backend.rebuild(tenant, version, f'actual-crash-{repeat}', datetime.now(timezone.utc))
            start = time.monotonic()
            process = await asyncio.to_thread(subprocess.run, [sys.executable, str(Path(__file__)), 'child', str(tenant)],
                                             capture_output=True, text=True, timeout=30)
            assert process.returncode == 77
            job_id = UUID(process.stdout.strip())
            # Wait the real default lease, not an edited clock or shortened test lease.
            await asyncio.sleep(30.3)
            outcome = await worker.run_once(tenant, 'replacement-process')
            with psycopg.connect(config['root_dsn']) as c:
                status, attempts = c.execute('SELECT status,attempts FROM jobs WHERE job_id=%s',(job_id,)).fetchone()
                vectors = c.execute('SELECT count(*) FROM memory_embeddings WHERE tenant_id=%s AND memory_version_id=%s',(tenant,version)).fetchone()[0]
            item = {'repeat':repeat+1, 'child_exit':process.returncode,'default_lease_seconds':30,
                    'recovery_seconds':time.monotonic()-start,'status':status,'attempts':attempts,
                    'outcome':outcome.outcome,'vector_rows_for_version':vectors}
            assert outcome.outcome == 'succeeded' and status == 'succeeded' and attempts == 2 and vectors == 1
            results.append(item); print(json.dumps(item),flush=True)
        report = {'scenario':'F5','observations':results,'passed':True,'model_calls':0,
                  'method':'Three actual subprocess os._exit deaths after committed native backend claim; default 30 second lease expires on real clock; frozen replacement EmbeddingWorker, exact precomputed Tencent native vectors; isolated synthetic clone. No SQL job status edits.'}
        target = ROOT/'docs/reports/phase2-b0-completion-2026-10-28/worker-crash.json'
        target.write_text(json.dumps(report,indent=2)+'\n')
    finally:
        await engine.dispose(); provider.db.close()


if __name__ == '__main__':
    asyncio.run(child(sys.argv[2]) if len(sys.argv)>1 else main())
