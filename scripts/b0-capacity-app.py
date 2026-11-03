"""Serve immutable B0 in an isolated fixture; instrument outside business code."""
import argparse
import asyncio
import contextvars
from contextlib import asynccontextmanager
import json
import sqlite3
import sys
import time
from array import array
from pathlib import Path
from uuid import UUID

REPO = Path(__file__).resolve().parents[1]
SOURCE = REPO / '.local/phase2/b0/source-B0'
sys.path.insert(0, str(SOURCE / 'src'))
import psycopg
import uvicorn
from sqlalchemy import event

from agent_memory.api.app import create_app
from agent_memory.application.embedding import EmbeddingWorker
from agent_memory.config import Settings
from agent_memory.infrastructure.db import create_session_factory
from agent_memory.infrastructure.embedding import PostgresEmbeddingBackend

CAP = REPO / '.local/phase2/b0/completion-20261028/capacity'
request_measure = contextvars.ContextVar('b0_request_measure', default=None)


class Precomputed:
    model = 'kinfra-text-embedding-0.6b'

    def __init__(self):
        self.db = sqlite3.connect('file:' + str(CAP / 'vectors-private.sqlite') + '?mode=ro', uri=True)

    async def embed(self, content):
        row = self.db.execute('SELECT vector FROM vectors WHERE text=?', (content,)).fetchone()
        if row is None:
            raise ValueError('NO_PRECOMPUTED_VECTOR_NO_EXTERNAL_FALLBACK')
        value = array('f'); value.frombytes(row[0]); assert len(value) == 1024
        return value.tolist()


class Measure:
    def __init__(self, app, log, query_map):
        self.app, self.log, self.query_map = app, log, query_map

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        started = time.perf_counter()
        values = {'at': time.time(), 'path': scope['path'], 'sql_ms': {}, 'status': None}
        token = request_measure.set(values)
        # Preserve original UTF8 wire length with opaque placeholders; raw benchmark queries never leave server.
        if scope['path'] in ('/v1/memories/search', '/v1/memories/context') and self.query_map:
            chunks = []
            while True:
                chunk = await receive(); chunks.append(chunk.get('body', b''))
                if not chunk.get('more_body', False):
                    break
            body = b''.join(chunks)
            try:
                payload = json.loads(body)
                code = payload.get('query', '').split(':', 1)[0]
                if code in self.query_map:
                    payload['query'] = self.query_map[code]
                    body = json.dumps(payload, ensure_ascii=False).encode()
                    scope = {**scope, 'headers': [(k, v) for k, v in scope['headers'] if k != b'content-length'] + [(b'content-length', str(len(body)).encode())]}
            except (ValueError, AttributeError):
                pass
            delivered = False
            async def receive_body():
                nonlocal delivered
                if delivered:
                    return await receive()
                delivered = True
                return {'type': 'http.request', 'body': body, 'more_body': False}
        else:
            receive_body = receive
        async def measured_send(message):
            if message['type'] == 'http.response.start':
                values['status'] = message['status']
                values['server_header_ms'] = (time.perf_counter() - started) * 1000
                message = {**message, 'headers': list(message.get('headers', [])) + [
                    (b'x-b0-server-ms', f"{values['server_header_ms']:.6f}".encode())]}
            await send(message)
        try:
            await self.app(scope, receive_body, measured_send)
        finally:
            values['server_total_ms'] = (time.perf_counter() - started) * 1000
            with self.log.open('a') as stream:
                stream.write(json.dumps(values) + '\n')
            request_measure.reset(token)


def install_pool_measurement(engine):
    # Evaluation-only wrappers on this engine instance; immutable SUT source is untouched.
    pool = engine.sync_engine.pool
    original_get = pool._pool.get
    def measured_get(block=True, timeout=None):
        started = time.perf_counter()
        values = request_measure.get()
        try:
            return original_get(block, timeout)
        finally:
            if values is not None:
                values.setdefault('pool_acquisitions', []).append({
                    'blocking': bool(block), 'queue_get_ms': (time.perf_counter()-started)*1000})
    pool._pool.get = measured_get
    original_create = pool._create_connection
    def measured_create():
        started = time.perf_counter()
        try:
            return original_create()
        finally:
            values = request_measure.get()
            if values is not None:
                values.setdefault('pool_connection_create_ms', []).append((time.perf_counter()-started)*1000)
    pool._create_connection = measured_create

def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--log', type=Path, required=True); parser.add_argument('--trace-console', action='store_true')
    args = parser.parse_args(); config = json.loads(args.config.read_text())
    settings = Settings(database_url=config['database_url'], jwt_public_key=(CAP / 'jwt-public.pem').read_text(),
        jwt_issuer='b0-capacity', jwt_audience='b0-capacity', embedding_model='kinfra-text-embedding-0.6b',
        embedding_endpoint='', extraction_endpoint='', extraction_model='deepseek-v4-pro',
        log_level='INFO' if args.trace_console else 'ERROR', trace_exporter='console' if args.trace_console else 'none',
        metrics_exporter='console' if args.trace_console else 'none')
    app = create_app(settings)
    @app.get('/health')
    async def health():
        return {'fixture': 'frozen-b0-isolated', 'ready': True}
    @event.listens_for(app.state.engine.sync_engine, 'before_cursor_execute')
    def before(conn, cursor, statement, parameters, context, executemany):
        conn.info['b0_query_start'] = time.perf_counter()
    @event.listens_for(app.state.engine.sync_engine, 'after_cursor_execute')
    def after(conn, cursor, statement, parameters, context, executemany):
        values = request_measure.get()
        if values is None:
            return
        category = 'vector_sql' if '<=>' in statement else ('lexical_sql' if 'tsquery' in statement else ('structured_sql' if 'memory_versions' in statement and 'ORDER BY' in statement else 'other_sql'))
        elapsed = (time.perf_counter() - conn.info.pop('b0_query_start', time.perf_counter())) * 1000
        values['sql_ms'][category] = values['sql_ms'].get(category, 0) + elapsed
    install_pool_measurement(app.state.engine)
    @event.listens_for(app.state.engine.sync_engine, 'handle_error')
    def failed_sql(context):
        values = request_measure.get()
        connection = context.connection
        if values is not None and connection is not None:
            started = connection.info.pop('b0_query_start', None)
            if started is not None:
                values.setdefault('failed_sql_ms', []).append((time.perf_counter()-started)*1000)
    provider = Precomputed(); worker = EmbeddingWorker(PostgresEmbeddingBackend(create_session_factory(app.state.engine)), provider)
    async def work():
        gate = asyncio.Semaphore(4)
        async def one(tenant):
            async with gate:
                await worker.run_once(UUID(tenant), 'b0-capacity-background')
        while True:
            def pending():
                with psycopg.connect(config['root_dsn']) as connection:
                    return [str(r[0]) for r in connection.execute("SELECT DISTINCT tenant_id FROM jobs WHERE status IN ('pending','retry_wait','running') LIMIT 1000")]
            try:
                tenants = await asyncio.to_thread(pending)
                await asyncio.gather(*(one(t) for t in tenants))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                print(json.dumps({'worker_error_class': type(exc).__name__}), flush=True)
            await asyncio.sleep(.5)
    original_lifespan = app.router.lifespan_context
    @asynccontextmanager
    async def lifespan(application):
        async with original_lifespan(application):
            task = asyncio.create_task(work())
            try:
                yield
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                provider.db.close()
    app.router.lifespan_context = lifespan
    query_file = CAP / 'query-map-private.json'
    query_map = json.loads(query_file.read_text()) if query_file.exists() else {}
    args.log.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    measured = Measure(app, args.log, query_map)
    net = CAP.parent / 'network'
    uvicorn.run(measured, host='127.0.0.1', port=18443, access_log=False,
        ssl_keyfile=str(net / 'key.pem'), ssl_certfile=str(net / 'cert.pem'))


if __name__ == '__main__':
    main()
