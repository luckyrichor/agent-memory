"""Require actual HTTP fault delivery before accepting query-vector fallback evidence."""
import asyncio
import importlib.util
import json
from pathlib import Path
import time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from threading import Thread
from uuid import uuid5,UUID

import httpx
import jwt
import psycopg

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('seed',ROOT/'scripts/prepare-b0-capacity-db.py')
seed=importlib.util.module_from_spec(spec);spec.loader.exec_module(seed)
from agent_memory.api.app import create_app
from agent_memory.config import Settings


async def main():
    cap=seed.CAP;cfg=json.loads((cap/'remaining-faults-config-private.json').read_text())
    with psycopg.connect(cfg['root_dsn']) as c:
        tenant,owner,content,memid=c.execute('SELECT m.tenant_id,m.owner_user_id,v.content,m.memory_id FROM memories m JOIN memory_versions v ON v.tenant_id=m.tenant_id AND v.memory_version_id=m.current_version_id WHERE m.tenant_id=(SELECT tenant_id FROM memories GROUP BY tenant_id ORDER BY count(*) LIMIT 1) ORDER BY m.memory_id LIMIT 1').fetchone()
    now=int(time.time());token=jwt.encode({'iss':'b0-fault','aud':'b0-fault','iat':now,'exp':now+1800,'tenant_id':str(tenant),'sub':str(owner),'permissions':['memory:read'],'allowed_workspace_ids':['pf']},(cap/'jwt-private.pem').read_text(),algorithm='RS256')
    rows=[]
    for repeat in range(3):
        for mode in [503,429,'timeout']:
            calls=[]
            class Handler(BaseHTTPRequestHandler):
                def log_message(self,*args):pass
                def do_POST(self):
                    self.rfile.read(int(self.headers['Content-Length']));calls.append(time.monotonic())
                    if mode=='timeout':time.sleep(4)
                    try:self.send_response(503 if mode=='timeout' else mode);self.send_header('Content-Length','2');self.end_headers();self.wfile.write(b'{}')
                    except (BrokenPipeError,ConnectionResetError):pass
            server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.daemon_threads=True;thread=Thread(target=server.serve_forever,daemon=True);thread.start()
            settings=Settings(database_url=cfg['database_url'],jwt_public_key=(cap/'jwt-public.pem').read_text(),jwt_issuer='b0-fault',jwt_audience='b0-fault',embedding_endpoint=f'http://127.0.0.1:{server.server_port}/embeddings',embedding_model='kinfra-text-embedding-0.6b',embedding_token='isolated-fixture-not-a-vendor-key',embedding_trust_env=False,log_level='ERROR',trace_exporter='none',metrics_exporter='none')
            app=create_app(settings)
            try:
                async with app.router.lifespan_context(app):
                    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app,raise_app_exceptions=False),base_url='http://fixture') as client:
                        start=time.monotonic();r=await client.post('/v1/memories/search',headers={'Authorization':'Bearer '+token},json={'query':content,'workspace_id':'pf','limit':10});d=r.json();elapsed=time.monotonic()-start
                        assert len(calls)==1, 'HTTP_FAULT_DID_NOT_REACH_FIXTURE'
                        assert r.status_code==200 and d['vector_status']=='degraded' and d['channel_counts']['vector']==0
                        if mode=='timeout':assert elapsed>=settings.query_embedding_timeout_seconds
                        row={'repeat':repeat+1,'failure':mode,'actual_http_fixture_calls':len(calls),'http':r.status_code,'vector_status':d['vector_status'],'channel_counts':d['channel_counts'],'target_at10':str(memid) in {x['memory_id'] for x in d['items']},'seconds':elapsed,'passed':True};rows.append(row);print(json.dumps(row),flush=True)
            finally:server.shutdown();server.server_close();thread.join(timeout=2)
    report={'scenario':'F3_search_degradation','observations':rows,'passed':True,'external_vendor_calls':0,'method':'Actual HTTP fixture receipt verified for each fault, explicit dummy fixture credential, default native query timeout3s, frozen ASGI route and PostgreSQL lexical/structured fallback. Synthetic data only. No server OS clock or job-state edits.'}
    (ROOT/'docs/reports/phase2-b0-completion-2026-10-28/search-degradation-verified.json').write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__':asyncio.run(main())
