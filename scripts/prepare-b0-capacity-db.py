"""Bulk seed a separate frozen B0 database using real precomputed native vectors."""
import argparse
import asyncio
import hashlib
import json
import sqlite3
import subprocess
import sys
import time
from array import array
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4, uuid5

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / '.local/phase2/b0/source-B0'
sys.path.insert(0, str(SOURCE / 'src'))
from alembic import command
from alembic.config import Config
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb
from sqlalchemy import DateTime, Float, Integer, SmallInteger, JSON, String
from sqlalchemy.dialects.postgresql import UUID as PGUUID

from agent_memory.application.embedding import EmbeddingWorker
from agent_memory.domain.enums import MemoryType, ScopeKind
from agent_memory.domain.models import Memory, MemoryScope
from agent_memory.infrastructure.db import create_engine, create_session_factory
from agent_memory.infrastructure.embedding import PostgresEmbeddingBackend
from agent_memory.infrastructure.orm import MemoryRow, MemoryVersionRow
from agent_memory.infrastructure.repositories import PostgresMemoryRepository

CAP = ROOT / '.local/phase2/b0/completion-20261028/capacity'
NAMESPACE = UUID('139e4480-c861-4fb4-b56c-2d70de78d926')


def tenant_for(index, count):
    number = 0 if index % 5 else 1 + (index // 5) % (count - 1)
    return uuid5(NAMESPACE, f'tenant:{count}:{number}')


def copy_rows(connection, table, rows):
    columns = list(table.columns)
    kinds = []
    for column in columns:
        kind = column.type
        if isinstance(kind, PGUUID):
            kinds.append('uuid')
        elif isinstance(kind, SmallInteger):
            kinds.append('int2')
        elif isinstance(kind, Integer):
            kinds.append('int4')
        elif isinstance(kind, Float):
            kinds.append('float8')
        elif isinstance(kind, DateTime):
            kinds.append('timestamptz')
        elif isinstance(kind, JSON):
            kinds.append('jsonb')
        elif isinstance(kind, String):
            kinds.append('text')
        else:
            raise ValueError('unmapped COPY type ' + str(kind))
    statement = sql.SQL('COPY {} ({}) FROM STDIN (FORMAT BINARY)').format(
        sql.Identifier(table.name), sql.SQL(',').join(sql.Identifier(c.name) for c in columns))
    with connection.cursor().copy(statement) as copy:
        copy.set_types(kinds)
        for row in rows:
            copy.write_row(tuple(Jsonb(getattr(row, c.name)) if kind == 'jsonb' else getattr(row, c.name)
                                 for c, kind in zip(columns, kinds, strict=True)))


class Precomputed:
    model = 'kinfra-text-embedding-0.6b'

    def __init__(self):
        self.db = sqlite3.connect('file:' + str(CAP / 'vectors-private.sqlite') + '?mode=ro', uri=True)

    async def embed(self, content):
        row = self.db.execute('SELECT vector FROM vectors WHERE text=?', (content,)).fetchone()
        if row is None:
            raise ValueError('PRECOMPUTED_TEXT_MISSING_NO_EXTERNAL_FALLBACK')
        vector = array('f'); vector.frombytes(row[0])
        assert len(vector) == 1024
        return vector.tolist()


async def embed_seed(url, tenants):
    engine = create_engine(url); sessions = create_session_factory(engine)
    provider = Precomputed(); worker = EmbeddingWorker(PostgresEmbeddingBackend(sessions), provider)
    gate = asyncio.Semaphore(8)
    outcomes = []
    async def drain(tenant, index):
        async with gate:
            while True:
                result = await worker.run_once(tenant, 'capacity-seed-' + str(index))
                if result.outcome == 'no_job':
                    return
                outcomes.append(result.outcome)
                if result.outcome != 'succeeded':
                    raise RuntimeError('SEED_EMBEDDING_JOB_FAILED')
    try:
        await asyncio.gather(*(drain(tenant, index) for tenant in tenants for index in range(4)))
    finally:
        await engine.dispose(); provider.db.close()
    return len(outcomes)


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--size', type=int, choices=[10000, 100000], required=True)
    parser.add_argument('--tenants', type=int, choices=[10, 100, 1000], default=100); args = parser.parse_args()
    CAP.mkdir(parents=True, exist_ok=True, mode=0o700)
    statefile = CAP / 'database-config-private.json'
    if not statefile.exists():
        password = uuid4().hex
        env = CAP / 'postgres-private.env'
        env.write_text('POSTGRES_USER=agent_memory\nPOSTGRES_DB=postgres\nPOSTGRES_PASSWORD=' + password + '\n'); env.chmod(0o600)
        subprocess.run(['docker', 'run', '-d', '--name', 'agent-memory-b0-capacity-20261028', '--cpus=2', '--memory=3g', '--shm-size=512m',
            '--memory-swap=3g', '-p', '127.0.0.1:56432:5432', '--env-file', str(env), 'pgvector/pgvector:pg16',
            '-c', 'shared_buffers=512MB', '-c', 'work_mem=8MB', '-c', 'maintenance_work_mem=256MB', '-c', 'max_connections=60'],
            check=True, stdout=subprocess.DEVNULL)
        config = {'password': password, 'root_dsn': f'host=127.0.0.1 port=56432 user=agent_memory password={password} dbname=postgres',
            'container': 'agent-memory-b0-capacity-20261028'}
        statefile.write_text(json.dumps(config) + '\n'); statefile.chmod(0o600)
    config = json.loads(statefile.read_text())
    for _ in range(60):
        try:
            with psycopg.connect(config['root_dsn'], autocommit=True) as connection:
                connection.execute('SELECT 1')
            break
        except psycopg.OperationalError:
            time.sleep(.5)
    name = f'b0pf_seed_{args.size}_{args.tenants}'
    with psycopg.connect(config['root_dsn'], autocommit=True) as connection:
        if connection.execute('SELECT 1 FROM pg_database WHERE datname=%s', (name,)).fetchone():
            raise ValueError('existing seed database is immutable; use its recorded manifest')
        connection.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
        if not connection.execute("SELECT 1 FROM pg_roles WHERE rolname='b0_pf_app'").fetchone():
            connection.execute(sql.SQL('CREATE ROLE b0_pf_app LOGIN PASSWORD {} NOSUPERUSER NOBYPASSRLS').format(sql.Literal(config['password'])))
    root_url = f'postgresql+psycopg://agent_memory:{config["password"]}@127.0.0.1:56432/{name}'
    alembic = Config(str(SOURCE / 'alembic.ini')); alembic.set_main_option('script_location', str(SOURCE / 'migrations'))
    alembic.set_main_option('sqlalchemy.url', root_url); command.upgrade(alembic, 'head')
    with psycopg.connect(config['root_dsn'], autocommit=True) as connection:
        connection.execute('GRANT agent_memory_app TO b0_pf_app')
    vectors = sqlite3.connect(CAP / 'vectors-private.sqlite')
    vectors.execute('CREATE INDEX IF NOT EXISTS vectors_text ON vectors(text)'); vectors.commit()
    count = vectors.execute('SELECT count(*) FROM vectors WHERE id < ?', (args.size,)).fetchone()[0]
    assert count == args.size, 'complete unique precomputed prefix required; no duplication/perturbation'
    started = time.monotonic(); tenants = set()
    dsn = config['root_dsn'].replace('dbname=postgres', 'dbname=' + name)
    with psycopg.connect(dsn) as connection:
        for start in range(0, args.size, 1000):
            memory_rows, version_rows = [], []
            for index, text in vectors.execute('SELECT id,text FROM vectors WHERE id>=? AND id<? ORDER BY id', (start, start+1000)):
                tenant = tenant_for(index, args.tenants); tenants.add(tenant)
                memory, version = Memory.create(tenant_id=tenant, memory_id=uuid5(NAMESPACE, f'memory:{index}'),
                    version_id=uuid5(NAMESPACE, f'version:{index}'), memory_type=MemoryType.EPISODIC,
                    scope=MemoryScope(ScopeKind.WORKSPACE, 'pf', None), owner_user_id=uuid5(NAMESPACE, str(tenant)),
                    content=text, now=datetime(2026, 10, 28, tzinfo=timezone.utc))
                memory_rows.append(PostgresMemoryRepository._memory_row(memory))
                version_rows.append(PostgresMemoryRepository._version_row(version))
            copy_rows(connection, MemoryRow.__table__, memory_rows)
            copy_rows(connection, MemoryVersionRow.__table__, version_rows)
            connection.commit()
    vectors.close()
    app_url = f'postgresql+psycopg_async://b0_pf_app:{config["password"]}@127.0.0.1:56432/{name}'
    completed = asyncio.run(embed_seed(app_url, sorted(tenants, key=str)))
    assert completed == args.size
    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute('ANALYZE')
        stats = {'memories': connection.execute('SELECT count(*) FROM memories').fetchone()[0],
            'vectors': connection.execute('SELECT count(*) FROM memory_embeddings').fetchone()[0],
            'pgvector': connection.execute("SELECT extversion FROM pg_extension WHERE extname='vector'").fetchone()[0],
            'postgres': connection.execute('SELECT version()').fetchone()[0],
            'database_bytes': connection.execute('SELECT pg_database_size(current_database())').fetchone()[0]}
    if not (CAP / 'jwt-private.pem').exists():
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        private = CAP / 'jwt-private.pem'; private.write_bytes(key.private_bytes(serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8, serialization.NoEncryption())); private.chmod(0o600)
        public = CAP / 'jwt-public.pem'; public.write_bytes(key.public_key().public_bytes(serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo)); public.chmod(0o600)
    appconfig = {'database_url': app_url, 'root_dsn': dsn, 'database': name,
        'tenants': [str(t) for t in sorted(tenants, key=str)], 'seed_size': args.size,
        'tenant_count': args.tenants, 'model': 'kinfra-text-embedding-0.6b'}
    private = CAP / f'{name}-private.json'; private.write_text(json.dumps(appconfig) + '\n'); private.chmod(0o600)
    report = {'database': name, 'size': args.size, 'tenants': args.tenants, 'heavy_tenant_fraction': .8,
        'seed_import_seconds': time.monotonic()-started, 'real_embedding_jobs_succeeded': completed,
        'no_real_model_calls_during_import': True, 'stats': stats,
        'method': 'Frozen domain/repository row constructors, checked FK/trigger binary COPY, original actual EmbeddingWorker with exact precomputed native real vectors; no status/lease bypass',
        'baseline_commit': subprocess.check_output(['git', '-C', str(SOURCE), 'rev-parse', 'HEAD'], text=True).strip()}
    (CAP / f'{name}-manifest.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
