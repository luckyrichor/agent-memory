"""Resume existing capacity jobs through frozen workers without changing job state."""
import asyncio
from collections import Counter
import importlib.util
import json
from pathlib import Path
import time
from uuid import UUID

import psycopg

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('capacity_seed', ROOT/'scripts/prepare-b0-capacity-db.py')
seed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seed)


async def main():
    cap = seed.CAP
    config = json.loads((cap/'b0pf_seed_10000_100-private.json').read_text())
    name = 'b0pf_seed_100000_100'
    for key in ('database_url', 'root_dsn'):
        config[key] = config[key].replace('b0pf_seed_10000_100', name)
    config.update(database=name, seed_size=100000)
    path = cap/f'{name}-private.json'
    path.write_text(json.dumps(config)+'\n'); path.chmod(0o600)
    engine = seed.create_engine(config['database_url'])
    provider = seed.Precomputed()
    worker = seed.EmbeddingWorker(seed.PostgresEmbeddingBackend(seed.create_session_factory(engine)), provider)
    outcomes = Counter(); start = time.monotonic(); rounds = 0
    gate = asyncio.Semaphore(2)
    async def drain(tenant):
        async with gate:
            for _ in range(100):
                result = await worker.run_once(UUID(tenant), 'capacity-seed-resume')
                outcomes[result.outcome+':'+result.reason_code] += 1
                if result.outcome != 'succeeded':
                    return
    try:
        while True:
            with psycopg.connect(config['root_dsn']) as connection:
                counts = dict(connection.execute('SELECT status,count(*) FROM jobs GROUP BY status'))
                tenants = [str(r[0]) for r in connection.execute("SELECT DISTINCT tenant_id FROM jobs WHERE status IN ('pending','running','retry_wait') ORDER BY tenant_id")]
            print(json.dumps({'seconds':time.monotonic()-start,'jobs':counts,'outcomes':dict(outcomes)}), flush=True)
            if counts.get('dead', 0):
                raise RuntimeError('DEAD_JOBS_REQUIRE_DIAGNOSIS')
            if not tenants:
                break
            await asyncio.gather(*(drain(t) for t in tenants))
            rounds += 1
            if rounds > 3000:
                raise RuntimeError('BOUNDED_RESUME_LIMIT')
            await asyncio.sleep(1)
        with psycopg.connect(config['root_dsn'], autocommit=True) as connection:
            connection.execute('ANALYZE')
            stats = {'memories': connection.execute('SELECT count(*) FROM memories').fetchone()[0],
                     'vectors': connection.execute('SELECT count(*) FROM memory_embeddings').fetchone()[0],
                     'pgvector': connection.execute("SELECT extversion FROM pg_extension WHERE extname='vector'").fetchone()[0],
                     'postgres': connection.execute('SELECT version()').fetchone()[0],
                     'database_bytes': connection.execute('SELECT pg_database_size(current_database())').fetchone()[0]}
        assert stats['memories'] == stats['vectors'] == counts.get('succeeded') == 100000
        result = {'database':name,'size':100000,'tenants':100,'heavy_tenant_fraction':.8,
                  'real_embedding_jobs_succeeded':counts['succeeded'],'stats':stats,
                  'resumed_after_initial_seed_failure':True,'resume_seconds':time.monotonic()-start,
                  'outcomes':dict(outcomes),'no_real_model_calls_during_import':True,
                  'method':'Exact precomputed native Tencent vectors; original frozen worker, actual lease clock and retries, no SQL job status changes',
                  'baseline_commit':'1e9d6f3b25b58c85792344000d7e1b5a71a79737'}
        (cap/f'{name}-manifest.json').write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps(result), flush=True)
    finally:
        await engine.dispose(); provider.db.close()


if __name__ == '__main__':
    asyncio.run(main())
