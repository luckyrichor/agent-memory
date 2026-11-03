"""Portable full table checksums, fixed random1000 row checks and frozen fused retrieval."""
import argparse
import asyncio
import hashlib
import json
import random
import sys
import time
from pathlib import Path
from uuid import UUID

import psycopg
from psycopg import sql


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--config', type=Path, required=True); parser.add_argument('--sample', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True); parser.add_argument('--create-sample', action='store_true')
    parser.add_argument('--queries', type=int, default=32)
    args = parser.parse_args();
    if args.queries < 1: parser.error('--queries must be positive')
    config = json.loads(args.config.read_text()); started = time.monotonic()
    sys.path.insert(0, str(args.source))
    from agent_memory.application.retrieval import MemoryRetriever, RetrievalQuery
    from agent_memory.domain.principal import RequestPrincipal
    from agent_memory.infrastructure.db import create_engine, create_session_factory, session_for_principal
    from agent_memory.infrastructure.retrieval import PostgresCandidateProvider
    table_hashes = {}
    with psycopg.connect(config['root_dsn']) as connection:
        connection.execute("SET TIME ZONE 'UTC'")
        tables = [r[0] for r in connection.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")]
        for table in tables:
            count, checksum = connection.execute(sql.SQL("SELECT count(*),md5(coalesce(string_agg(h,'' ORDER BY h),'')) FROM (SELECT md5(to_jsonb(t)::text) h FROM {} t) a").format(sql.Identifier(table))).fetchone()
            table_hashes[table] = {'rows': count, 'canonical_json_md5_multiset_checksum': checksum}
        if args.create_sample:
            ids = connection.execute('SELECT tenant_id,memory_id FROM memories ORDER BY tenant_id,memory_id').fetchall()
            chosen = random.Random(2026102802).sample(ids, min(1000, len(ids)))
            sample = [{'tenant_id': str(t), 'memory_id': str(m)} for t, m in chosen]
            args.sample.write_text(json.dumps(sample) + '\n'); args.sample.chmod(0o600)
        else:
            sample = json.loads(args.sample.read_text())
        records = []
        for item in sample:
            row = connection.execute('SELECT m.owner_user_id,v.content,e.embedding::text,md5(to_jsonb(m)::text),md5(to_jsonb(v)::text),md5(to_jsonb(e)::text) FROM memories m JOIN memory_versions v ON v.tenant_id=m.tenant_id AND v.memory_version_id=m.current_version_id JOIN memory_embeddings e ON e.tenant_id=m.tenant_id AND e.memory_version_id=m.current_version_id WHERE m.tenant_id=%s AND m.memory_id=%s',
                (item['tenant_id'], item['memory_id'])).fetchone()
            if row is None:
                raise RuntimeError('RESTORE_SAMPLE_ROW_MISSING')
            records.append({**item, 'owner_user_id': str(row[0]), 'text': row[1], 'vector': json.loads(row[2]), 'row_checksums': list(row[3:])})
        environment = {'postgres': connection.execute('SELECT version()').fetchone()[0],
            'pgvector': connection.execute("SELECT extversion FROM pg_extension WHERE extname='vector'").fetchone()[0],
            'rls': [list(r) for r in connection.execute("SELECT relname,relrowsecurity,relforcerowsecurity FROM pg_class WHERE relnamespace='public'::regnamespace AND relkind='r' ORDER BY relname")],
            'roles': [list(r) for r in connection.execute("SELECT rolname,rolsuper,rolbypassrls,rolinherit,rolcanlogin FROM pg_roles WHERE rolname IN ('agent_memory','agent_memory_app','b0_pf_app') ORDER BY rolname")]}
    async def verify():
        query_rows = random.Random(2026102803).sample(records, min(args.queries, len(records)))
        engine = create_engine(config['database_url']); sessions = create_session_factory(engine)
        gate = asyncio.Semaphore(4); results = []
        async def one(row):
            principal = RequestPrincipal(UUID(row['tenant_id']), UUID(row['owner_user_id']), frozenset(), frozenset({'memory:read'}), frozenset({'pf'}))
            async with gate:
                async with session_for_principal(sessions, principal) as session:
                    page = await MemoryRetriever(PostgresCandidateProvider(session)).search(
                        RetrievalQuery(row['text'], tuple(row['vector']), 'kinfra-text-embedding-0.6b', workspace_id='pf', limit=10), principal)
                results.append({'tenant_id': row['tenant_id'], 'memory_id': row['memory_id'],
                    'row_checksums': row['row_checksums'], 'top10': [str(r.memory_id) for r in page.items],
                    'RT1_at10': row['memory_id'] in {str(r.memory_id) for r in page.items}})
        try:
            await asyncio.gather(*(one(row) for row in query_rows))
        finally:
            await engine.dispose()
        return sorted(results, key=lambda r: (r['tenant_id'], r['memory_id']))
    retrieval = asyncio.run(verify())
    # Real non-owner connection exercises restored FORCE RLS and privilege membership.
    from sqlalchemy.engine import make_url
    url = make_url(config['database_url'])
    dsn = f'host={url.host} port={url.port} user={url.username} password={url.password} dbname={url.database}'
    own = records[0]['tenant_id']; foreign = next(r['tenant_id'] for r in records if r['tenant_id'] != own)
    with psycopg.connect(dsn) as connection:
        connection.execute("SELECT set_config('app.current_tenant_id',%s,true)", (own,))
        leaked = connection.execute('SELECT count(*) FROM memories WHERE tenant_id=%s', (foreign,)).fetchone()[0]
        own_count = connection.execute('SELECT count(*) FROM memories WHERE tenant_id=%s', (own,)).fetchone()[0]
        flags = connection.execute('SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user').fetchone()
        assert leaked == 0 and own_count > 0 and not any(flags)
        denied_write = False
        try:
            with connection.transaction():
                connection.execute("INSERT INTO memories(tenant_id,memory_id,memory_type,status,scope_kind,workspace_id,visibility,owner_user_id,revision,created_at,updated_at) VALUES (%s,gen_random_uuid(),'episodic','active','workspace','pf','scope',gen_random_uuid(),1,now(),now())", (foreign,))
        except psycopg.errors.InsufficientPrivilege:
            denied_write = True
        assert denied_write
    result = {'tables': table_hashes, 'random_sample_rows': len(records),
        'sample_file_sha256': hashlib.sha256(args.sample.read_bytes()).hexdigest(),
        'sample_rows_checksums': [{k: r[k] for k in ('tenant_id','memory_id','row_checksums')} for r in records],
        'retrieval_query_count': len(retrieval), 'retrieval_selection_seed': 2026102803,
        'sample_and_retrieval': retrieval, 'RT1_at10': sum(r['RT1_at10'] for r in retrieval) / len(retrieval),
        'environment': environment, 'role_checks': {'cross_tenant_read_count': leaked, 'foreign_write_rejected': denied_write,
            'own_tenant_readable': own_count > 0, 'app_superuser': flags[0], 'app_bypassrls': flags[1]},
        'seconds': time.monotonic() - started,
        'method': 'all public table counts and canonical JSON row multiset checksums; same fixed random1000 rows; actual frozen MemoryRetriever and PostgresCandidateProvider all channels/fusion under non-owner app principals, same native vectors. Synthetic workload only; no model calls.'}
    args.output.write_text(json.dumps(result, ensure_ascii=False) + '\n'); args.output.chmod(0o600)
    print(json.dumps({'rows': len(records), 'RT1_at10': result['RT1_at10'], 'seconds': result['seconds'], 'role_checks': result['role_checks']}), flush=True)


if __name__ == '__main__':
    main()
