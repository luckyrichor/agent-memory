"""Actual loopback HTTP timeout/rate-limit/server-error recovery with frozen workers."""
import asyncio
from array import array
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
from pathlib import Path
import sys
from threading import Thread
import time

import httpx
import psycopg

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('seed', ROOT/'scripts/prepare-b0-capacity-db.py')
seed = importlib.util.module_from_spec(spec); spec.loader.exec_module(seed)
from agent_memory.infrastructure.embedding import HTTPEmbeddingProvider


async def main():
    cap = seed.CAP
    config_path = Path(sys.argv[sys.argv.index('--config')+1]) if '--config' in sys.argv else cap/'fault-config-private.json'
    cfg = json.loads(config_path.read_text())
    with psycopg.connect(cfg['root_dsn']) as c:
        tenant, version, text = c.execute('SELECT tenant_id,memory_version_id,content FROM memory_versions ORDER BY memory_version_id LIMIT 1').fetchone()
    precomputed = seed.Precomputed(); vector = await precomputed.embed(text); precomputed.db.close()
    state = {'calls':0,'mode':None}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            assert payload['input'] == text and payload['model'] == 'kinfra-text-embedding-0.6b'
            state['calls'] += 1; first = state['calls'] == 1 or '--exhaustion' in sys.argv
            if first and state['mode'] == 'timeout': time.sleep(11)
            status = int(state['mode']) if first and state['mode'] != 'timeout' else 200
            body = json.dumps({'data':[{'embedding':vector}]} if status == 200 else {'error':{'code':'FIXTURE'}}).encode()
            try:
                self.send_response(status)
                if status == 429: self.send_header('Retry-After','2')
                self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass
    server = ThreadingHTTPServer(('127.0.0.1',0),Handler);server.daemon_threads=True
    Thread(target=server.serve_forever,daemon=True).start()
    engine = seed.create_engine(cfg['database_url']); backend = seed.PostgresEmbeddingBackend(seed.create_session_factory(engine))
    results = []
    try:
        async with httpx.AsyncClient(trust_env=False,timeout=15) as client:
            provider = HTTPEmbeddingProvider(client,endpoint=f'http://127.0.0.1:{server.server_port}/embeddings',model='kinfra-text-embedding-0.6b',token='isolated-fixture-no-secret')
            worker = seed.EmbeddingWorker(backend,provider)
            if '--exhaustion' in sys.argv:
                state['mode'] = '503'
                for repeat in range(3):
                    state['calls'] = 0
                    await backend.rebuild(tenant,version,f'actual-http-exhaustion-v1-{repeat}',datetime.now(timezone.utc))
                    started = time.monotonic(); outcomes = []
                    for attempt in range(5):
                        result = await worker.run_once(tenant,'http-exhaustion-worker')
                        outcomes.append(result.outcome)
                        with psycopg.connect(cfg['root_dsn']) as c:
                            status,attempts,available = c.execute('SELECT status,attempts,available_at FROM jobs WHERE job_id=%s',(result.job_id,)).fetchone()
                        if attempt < 4:
                            assert result.outcome == status == 'retry_wait'
                            await asyncio.sleep(max(0,(available-datetime.now(timezone.utc)).total_seconds())+.1)
                        else:
                            assert result.outcome == status == 'dead' and attempts == 5
                    row={'repeat':repeat+1,'http_status':503,'http_attempts':state['calls'],'outcomes':outcomes,'final_status':status,'attempts':attempts,'seconds':time.monotonic()-started}
                    assert state['calls'] == 5
                    results.append(row);print(json.dumps(row),flush=True)
                report={'scenario':'F3_persistent_failure','observations':results,'passed':True,'external_model_calls':0,
                        'method':'Actual loopback HTTP503 on every attempt, native max_attempts5 and real database backoff, three repetitions; no SQL job status/time edits.',
                        'limitation':'Search-degradation response semantics remain separate; dead-letter correctness does not prove all F3 requirements.'}
                (ROOT/'docs/reports/phase2-b0-completion-2026-10-28/provider-exhaustion.json').write_text(json.dumps(report,indent=2)+'\n')
                return
            for repeat in range(3):
                for mode in ['timeout','429','503']:
                    state.update(calls=0,mode=mode)
                    await backend.rebuild(tenant,version,f'actual-http-{mode}-{repeat}',datetime.now(timezone.utc))
                    start = time.monotonic(); first = await worker.run_once(tenant,'http-fault-worker')
                    assert first.outcome == 'retry_wait'
                    with psycopg.connect(cfg['root_dsn']) as c:
                        available = c.execute('SELECT available_at FROM jobs WHERE job_id=%s',(first.job_id,)).fetchone()[0]
                    await asyncio.sleep(max(0,(available-datetime.now(timezone.utc)).total_seconds())+.1)
                    second = await worker.run_once(tenant,'http-replacement')
                    assert second.outcome == 'succeeded' and second.job_id == first.job_id
                    with psycopg.connect(cfg['root_dsn']) as c:
                        status,attempts = c.execute('SELECT status,attempts FROM jobs WHERE job_id=%s',(first.job_id,)).fetchone()
                    assert status == 'succeeded' and attempts == 2
                    row = {'repeat':repeat+1,'mode':mode,'first_outcome':first.outcome,'reason_code':first.reason_code,'second_outcome':second.outcome,'attempts':attempts,'http_attempts':state['calls'],'seconds':time.monotonic()-start}
                    results.append(row);print(json.dumps(row),flush=True)
        report = {'scenario':'F3_partial','observations':results,'passed':True,'external_model_calls':0,
                  'method':'Actual loopback HTTP provider and frozen default worker timeout10s/lease30s. First request times out, returns429 Retry-After2, or503; actual persisted backoff then successful exact native precomputed vector. Three repeats each; no job state/clock edits.',
                  'limitation':'Transient recovery only; HTTP exhaustion/dead-letter and search degradation require separate coverage.'}
        (ROOT/'docs/reports/phase2-b0-completion-2026-10-28/provider-faults.json').write_text(json.dumps(report,indent=2)+'\n')
    finally:
        server.shutdown();server.server_close();await engine.dispose()


if __name__ == '__main__':
    asyncio.run(main())
