"""Fill only a16MiB disposable tablespace, then exercise the frozen HTTP API."""
import asyncio
import importlib.util
import json
import random
from pathlib import Path
import subprocess
import time
from uuid import uuid4

import httpx
import jwt
import psycopg
from psycopg import sql

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('seed',ROOT/'scripts/prepare-b0-capacity-db.py')
seed=importlib.util.module_from_spec(spec);spec.loader.exec_module(seed)
from agent_memory.api.app import create_app
from agent_memory.config import Settings


async def main():
    cap=seed.CAP;container='agent-memory-b0-diskfull-v2-20261031';password=uuid4().hex
    env=cap/'diskfull-v2-env-private.txt';env.write_text('POSTGRES_USER=agent_memory\nPOSTGRES_DB=fault\nPOSTGRES_PASSWORD='+password+'\n');env.chmod(0o600)
    subprocess.run(['docker','run','-d','--name',container,'--cpus=1','--memory=512m','--shm-size=64m','--tmpfs','/faultdisk:rw,size=16m','-p','127.0.0.1:56433:5432','--env-file',str(env),'pgvector/pgvector:pg16'],check=True,stdout=subprocess.DEVNULL)
    dsn=f'host=127.0.0.1 port=56433 user=agent_memory password={password} dbname=fault'
    confirmed=[];observations=[]
    try:
        for _ in range(60):
            try:
                with psycopg.connect(dsn,connect_timeout=1):pass
                break
            except psycopg.OperationalError:await asyncio.sleep(.5)
        with psycopg.connect(dsn,autocommit=True) as c:
            c.execute('CREATE ROLE agent_memory_app NOLOGIN NOSUPERUSER NOBYPASSRLS')
            c.execute(sql.SQL('CREATE ROLE b0_pf_app LOGIN PASSWORD {} NOSUPERUSER NOBYPASSRLS').format(sql.Literal(password)))
            c.execute('GRANT agent_memory_app TO b0_pf_app')
        dump=cap/'diskfull-seed-v2-private.dump'
        with dump.open('wb') as f:subprocess.run(['docker','exec','agent-memory-b0-capacity-20261028','pg_dump','-U','agent_memory','-d','b0pf_seed_10000_100','-Fc'],stdout=f,check=True)
        dump.chmod(0o600)
        with dump.open('rb') as f:subprocess.run(['docker','exec','-i',container,'pg_restore','--exit-on-error','-U','agent_memory','-d','fault'],stdin=f,check=True,stdout=subprocess.DEVNULL)
        subprocess.run(['docker','exec',container,'sh','-c','mkdir /faultdisk/tablespace && chown postgres:postgres /faultdisk/tablespace && chmod 700 /faultdisk/tablespace'],check=True)
        with psycopg.connect(dsn,autocommit=True) as c:
            c.execute("CREATE TABLESPACE b0_limited LOCATION '/faultdisk/tablespace'")
            c.execute('ALTER TABLE memory_versions SET TABLESPACE b0_limited')
            tenant,owner,memid=c.execute('SELECT tenant_id,owner_user_id,memory_id FROM memories ORDER BY memory_id LIMIT 1').fetchone()
        now=int(time.time());token=jwt.encode({'iss':'disk-fault','aud':'disk-fault','iat':now,'exp':now+1800,'tenant_id':str(tenant),'sub':str(owner),'permissions':['memory:read','memory:write'],'allowed_workspace_ids':['pf']},(cap/'jwt-private.pem').read_text(),algorithm='RS256')
        app=create_app(Settings(database_url=f'postgresql+psycopg://b0_pf_app:{password}@127.0.0.1:56433/fault',jwt_public_key=(cap/'jwt-public.pem').read_text(),jwt_issuer='disk-fault',jwt_audience='disk-fault',embedding_endpoint='',extraction_endpoint='',log_level='ERROR',trace_exporter='none',metrics_exporter='none'))
        captured=[]
        def sqlstates(exc,seen=None):
            seen=set() if seen is None else seen
            if id(exc) in seen:return []
            seen.add(id(exc));out=[]
            if getattr(exc,'sqlstate',None):out.append(exc.sqlstate)
            for child in [getattr(exc,'orig',None),getattr(exc,'__cause__',None),getattr(exc,'__context__',None)]+list(getattr(exc,'exceptions',[])):
                if child is not None:out.extend(sqlstates(child,seen))
            return out
        async def capture(scope,receive,send):
            try:await app(scope,receive,send)
            except Exception as exc:
                captured.extend(sqlstates(exc));raise
        write_number=0
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=capture,raise_app_exceptions=False),base_url='http://disk-fixture') as client:
                async def write():
                    nonlocal write_number
                    write_number+=1
                    rng=random.Random(write_number)
                    body={'content':'虚构磁盘演练：'+''.join(chr(0x4e00+rng.randrange(2000)) for _ in range(900)),'memory_type':'episodic','scope':{'kind':'workspace','workspace_id':'pf'}}
                    r=await client.post('/v1/memories',headers={'Authorization':'Bearer '+token,'Idempotency-Key':str(uuid4())},json=body)
                    if r.status_code==201:confirmed.append(r.json()['memory_id'])
                    return r
                for repeat in range(3):
                    pre=await write();assert pre.status_code==201
                    fill=subprocess.run(['docker','exec',container,'dd','if=/dev/zero','of=/faultdisk/filler','bs=1M','count=32'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                    assert fill.returncode!=0
                    with psycopg.connect(dsn) as c:
                        # PostgreSQL itself must observe the full dedicated filesystem.
                        full_size=c.execute("SELECT pg_tablespace_size('b0_limited')").fetchone()[0]
                    captured.clear();start=time.monotonic();failure=None
                    for _ in range(50):
                        r=await write()
                        if r.status_code>=500:failure=r.status_code;break
                        assert r.status_code==201, 'VALIDATION_FAILURE_NOT_DISK_FULL_EVIDENCE'
                    read=await client.get('/v1/memories/'+str(memid),headers={'Authorization':'Bearer '+token})
                    subprocess.run(['docker','exec',container,'rm','/faultdisk/filler'],check=True)
                    recovered=await write()
                    assert '53100' in captured, 'POSTGRES_DISK_FULL_SQLSTATE_REQUIRED'
                    assert failure is not None and read.status_code==200 and recovered.status_code==201
                    row={'repeat':repeat+1,'limited_filesystem_bytes':16777216,'tablespace_bytes':full_size,'failed_write_http':failure,'captured_sqlstates':sorted(set(captured)),'read_during_full_http':read.status_code,'write_after_cleanup_http':recovered.status_code,'seconds':time.monotonic()-start,'read_recovery_pass':True,'explicit_retryable_error_semantics_pass':failure in [503,507]};observations.append(row);print(json.dumps(row),flush=True)
                with psycopg.connect(dsn) as c:present=c.execute('SELECT count(*) FROM memories WHERE memory_id=ANY(%s::uuid[])',(confirmed,)).fetchone()[0]
                assert present==len(confirmed)
        report={'scenario':'F9','observations':observations,'confirmed_writes':len(confirmed),'confirmed_missing':len(confirmed)-present,'external_model_calls':0,'scope':'Separate1CPU/512MiB PostgreSQL container; only memory_versions physical tablespace relocated to a16MiB tmpfs. Schema/business code unchanged. Full-volume file removed between trials; host root disk was never filled. Read/recovery correctness distinct from error semantics.'}
        (ROOT/'docs/reports/phase2-b0-completion-2026-10-28/disk-full.json').write_text(json.dumps(report,indent=2)+'\n')
    finally:subprocess.run(['docker','stop','--time','2',container],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)


if __name__=='__main__':asyncio.run(main())
