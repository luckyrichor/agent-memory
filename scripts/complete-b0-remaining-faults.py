"""Bounded local fault observations against immutable B0, no vendor calls."""
import asyncio
from datetime import datetime,timezone,timedelta
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import importlib.util
import json
from pathlib import Path
from threading import Thread
import time

import httpx
import jwt
import psycopg
from psycopg import sql

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('seed',ROOT/'scripts/prepare-b0-capacity-db.py')
seed=importlib.util.module_from_spec(spec);spec.loader.exec_module(seed)
from agent_memory.api.app import create_app
from agent_memory.config import Settings
from agent_memory.domain.errors import LeaseLost

CAP=seed.CAP
PUBLIC=ROOT/'docs/reports/phase2-b0-completion-2026-10-28'


async def main():
    config=json.loads((CAP/'b0pf_seed_10000_100-private.json').read_text())
    name='b0_remaining_faults_20261031'
    with psycopg.connect(config['root_dsn'],autocommit=True) as c:
        assert not c.execute('SELECT 1 FROM pg_database WHERE datname=%s',(name,)).fetchone(), 'preserve existing run'
        c.execute(sql.SQL('CREATE DATABASE {} TEMPLATE {}').format(sql.Identifier(name),sql.Identifier(config['database'])))
    for key in ['root_dsn','database_url']:config[key]=config[key].replace(config['database'],name)
    config['database']=name
    private=CAP/'remaining-faults-config-private.json';private.write_text(json.dumps(config)+'\n');private.chmod(0o600)
    with psycopg.connect(config['root_dsn']) as c:
        tenant,owner,version,content,memid=c.execute('SELECT m.tenant_id,m.owner_user_id,v.memory_version_id,v.content,m.memory_id FROM memories m JOIN memory_versions v ON v.tenant_id=m.tenant_id AND v.memory_version_id=m.current_version_id WHERE m.tenant_id=(SELECT tenant_id FROM memories GROUP BY tenant_id ORDER BY count(*) LIMIT 1) ORDER BY m.memory_id LIMIT 1').fetchone()
    engine=seed.create_engine(config['database_url']);backend=seed.PostgresEmbeddingBackend(seed.create_session_factory(engine))
    provider=seed.Precomputed();worker=seed.EmbeddingWorker(backend,provider)
    report={'baseline_commit':'1e9d6f3b25b58c85792344000d7e1b5a71a79737','external_vendor_calls':0,'observations':[],
            'phase2_accepted':False,'method':'Fresh isolated clone; actual frozen API/worker/repository, real default leases and pool timeout; no SQL job state/time edits.'}
    def save(row):
        report['observations'].append(row)
        (PUBLIC/'remaining-faults.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps(row),flush=True)
    try:
        for repeat in range(3):
            for skew in [-120,120]:
                await backend.rebuild(tenant,version,f'skew-{repeat}-{skew}',datetime.now(timezone.utc))
                result=await worker.run_once(tenant,'skewed-clock-worker',now=datetime.now(timezone.utc)+timedelta(seconds=skew))
                with psycopg.connect(config['root_dsn']) as c:
                    status,attempts=c.execute('SELECT status,attempts FROM jobs WHERE job_id=%s',(result.job_id,)).fetchone()
                save({'scenario':'F12','repeat':repeat+1,'injected_application_clock_skew_seconds':skew,'outcome':result.outcome,'attempts':attempts,'passed':status=='succeeded' and attempts==1,
                      'scope':'Worker now dependency offset; repository fencing uses database clock. Host OS clocks unchanged.'})
        for repeat in range(3):
            await backend.rebuild(tenant,version,f'zombie-{repeat}',datetime.now(timezone.utc))
            old=await backend.claim(tenant,'zombie-old',datetime.now(timezone.utc),timedelta(seconds=30));assert old
            start=time.monotonic();await asyncio.sleep(30.2)
            replacement=await worker.run_once(tenant,'replacement')
            rejected=False
            try:await backend.complete(old,'zombie-old',provider.model,await provider.embed(content),datetime.now(timezone.utc))
            except LeaseLost:rejected=True
            save({'scenario':'F6','repeat':repeat+1,'default_lease_seconds':30,'real_wait_seconds':time.monotonic()-start,'replacement':replacement.outcome,'stale_vector_commit_rejected':rejected,'passed':rejected and replacement.outcome=='succeeded'})
        state={'mode':503,'calls':0}
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']));state['calls']+=1
                if state['mode']=='timeout':time.sleep(4)
                try:self.send_response(503 if state['mode']=='timeout' else state['mode']);self.send_header('Content-Length','2');self.end_headers();self.wfile.write(b'{}')
                except (BrokenPipeError,ConnectionResetError):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.daemon_threads=True;Thread(target=server.serve_forever,daemon=True).start()
        key=(CAP/'jwt-private.pem').read_text();now=int(time.time())
        token=jwt.encode({'iss':'b0-fault','aud':'b0-fault','iat':now,'exp':now+3600,'tenant_id':str(tenant),'sub':str(owner),'permissions':['memory:read'],'allowed_workspace_ids':['pf']},key,algorithm='RS256')
        def settings(endpoint=''):
            return Settings(database_url=config['database_url'],jwt_public_key=(CAP/'jwt-public.pem').read_text(),jwt_issuer='b0-fault',jwt_audience='b0-fault',embedding_model=provider.model,embedding_endpoint=endpoint,embedding_trust_env=False,log_level='ERROR',trace_exporter='none',metrics_exporter='none')
        try:
            for repeat in range(3):
                for mode in [503,429,'timeout']:
                    state.update(mode=mode,calls=0)
                    app=create_app(settings(f'http://127.0.0.1:{server.server_port}/embedding'))
                    async with app.router.lifespan_context(app):
                        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app,raise_app_exceptions=False),base_url='http://isolated') as client:
                            start=time.monotonic();response=await client.post('/v1/memories/search',headers={'Authorization':'Bearer '+token},json={'query':content,'workspace_id':'pf','limit':10})
                            data=response.json();hit=str(memid) in {r['memory_id'] for r in data.get('items',[])}
                            save({'scenario':'F3_search_degradation','repeat':repeat+1,'fixture_failure':mode,'http':response.status_code,'vector_status':data.get('vector_status'),'channel_counts':data.get('channel_counts'),'items':len(data.get('items',[])),'target_at10':hit,'seconds':time.monotonic()-start,'passed':response.status_code==200 and data.get('vector_status')=='degraded'})
            for repeat in range(3):
                app=create_app(settings())
                async with app.router.lifespan_context(app):
                    pool=app.state.engine.sync_engine.pool;capacity=pool.size()+pool._max_overflow
                    held=[]
                    try:
                        for _ in range(capacity):held.append(await app.state.engine.connect())
                        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app,raise_app_exceptions=False),base_url='http://isolated') as client:
                            start=time.monotonic();pending=asyncio.create_task(client.post('/v1/memories/search',headers={'Authorization':'Bearer '+token},json={'query':content,'workspace_id':'pf','limit':10}))
                            await asyncio.sleep(.2);independent=await client.get('/openapi.json');response=await asyncio.wait_for(pending,45)
                            save({'scenario':'F2','repeat':repeat+1,'occupied_pool_connections':capacity,'http':response.status_code,'seconds':time.monotonic()-start,'independent_static_endpoint_http':independent.status_code,'passed':False,'criterion':'Record actual error/latency; unhandled500 and approximately30s pool wait do not satisfy quick explicit retryable failure.'})
                    finally:
                        for conn in held:await conn.close()
        finally:server.shutdown();server.server_close()
        report['finished']=True;(PUBLIC/'remaining-faults.json').write_text(json.dumps(report,indent=2)+'\n')
    finally:await engine.dispose();provider.db.close()


if __name__=='__main__':asyncio.run(main())
