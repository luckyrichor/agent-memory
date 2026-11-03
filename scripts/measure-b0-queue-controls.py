"""Frozen PostgreSQL queue fault/lease controls in a new disposable database; no model calls."""
import asyncio
import hashlib
import json
import subprocess
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

REPO = Path(__file__).resolve().parents[1]
SOURCE = REPO / '.local/phase2/b0/source-B0'
sys.path.insert(0, str(SOURCE / 'src'))
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from testcontainers.community.postgres import PostgresContainer

from agent_memory.domain.errors import LeaseLost
from agent_memory.domain.principal import RequestPrincipal
from agent_memory.infrastructure.db import create_engine as async_engine
from agent_memory.infrastructure.db import create_session_factory, session_for_principal
from agent_memory.infrastructure.event_repositories import PostgresJobQueue
from agent_memory.infrastructure.orm import JobRow

PUBLIC = REPO / 'docs/reports/phase2-b0-evidence-supplement-2026-10-27'


async def exercise(url):
    engine = async_engine(url)
    sessions = create_session_factory(engine)
    observations = []
    try:
        for repeat in range(3):
            for scenario in ('normal', 'transient_retry', 'expired_owner', 'permanent_failure', 'retry_exhaustion'):
                tenant, job_id = uuid4(), uuid4()
                principal = RequestPrincipal(tenant, uuid4(), frozenset(), frozenset(), frozenset())
                now = datetime.now(timezone.utc)
                async with session_for_principal(sessions, principal) as session:
                    session.add(JobRow(tenant_id=tenant, job_id=job_id, job_type='extract_event',
                        idempotency_key=str(job_id), payload={'fixture': 'queue-only'}, status='pending',
                        attempts=0, max_attempts=2, available_at=now, leased_until=None, lease_owner=None,
                        last_error_code=None, created_at=now, updated_at=now))

                async def operation(name, *args, **kwargs):
                    async with session_for_principal(sessions, principal) as session:
                        return await getattr(PostgresJobQueue(session), name)(tenant, *args, **kwargs)

                lease = timedelta(milliseconds=120) if scenario == 'expired_owner' else timedelta(seconds=30)
                claimed = await operation('claim', 'worker-old', now, lease)
                assert claimed and claimed.job_id == job_id
                rejected = 0
                if scenario == 'expired_owner':
                    await asyncio.sleep(.2)
                    replacement = await operation('claim', 'worker-new', now, timedelta(seconds=30))
                    assert replacement and replacement.attempts == 2
                    for action in ('succeed', 'renew', 'fail'):
                        try:
                            if action == 'renew':
                                await operation(action, job_id, 'worker-old', now, timedelta(seconds=30))
                            elif action == 'fail':
                                await operation(action, job_id, 'worker-old', now, 'STALE', retryable=False)
                            else:
                                await operation(action, job_id, 'worker-old', now)
                        except LeaseLost:
                            rejected += 1
                    completed = await operation('succeed', job_id, 'worker-new', now)
                    assert completed.status.value == 'succeeded'
                elif scenario in ('transient_retry', 'retry_exhaustion'):
                    failed = await operation('fail', job_id, 'worker-old', now, 'FIXTURE_TRANSIENT', retryable=True)
                    assert failed.status.value == 'retry_wait'
                    # Respect the actual repository's database clock and backoff; no row/time rewriting.
                    await asyncio.sleep(max(0, (failed.available_at - datetime.now(timezone.utc)).total_seconds()) + .08)
                    retry = await operation('claim', 'worker-new', now, timedelta(seconds=30))
                    assert retry and retry.attempts == 2
                    if scenario == 'transient_retry':
                        await operation('succeed', job_id, 'worker-new', now)
                    else:
                        final = await operation('fail', job_id, 'worker-new', now, 'FIXTURE_TRANSIENT', retryable=True)
                        assert final.status.value == 'dead'
                elif scenario == 'permanent_failure':
                    final = await operation('fail', job_id, 'worker-old', now, 'FIXTURE_PERMANENT', retryable=False)
                    assert final.status.value == 'dead'
                else:
                    await operation('succeed', job_id, 'worker-old', now)
                async with session_for_principal(sessions, principal) as session:
                    row = (await session.execute(select(JobRow).where(JobRow.tenant_id == tenant, JobRow.job_id == job_id))).scalar_one()
                    observations.append({'repeat': repeat, 'scenario': scenario, 'status': row.status,
                        'attempts': row.attempts, 'stale_actions_rejected': rejected,
                        'stale_actions_attempted': 3 if scenario == 'expired_owner' else 0,
                        'lease_owner_after': row.lease_owner, 'model_calls': 0})
                assert scenario != 'expired_owner' or rejected == 3
    finally:
        await engine.dispose()
    return observations


def main():
    commit = subprocess.check_output(['git', '-C', str(SOURCE), 'rev-parse', 'HEAD'], text=True).strip()
    assert commit == '1e9d6f3b25b58c85792344000d7e1b5a71a79737'
    assert not subprocess.check_output(['git', '-C', str(SOURCE), 'status', '--porcelain'], text=True).strip()
    password = uuid4().hex
    with PostgresContainer('pgvector/pgvector:pg16', username='agent_memory', password=password,
                           dbname='agent_memory', driver='psycopg') as pg:
        url = pg.get_connection_url()
        config = Config(str(SOURCE / 'alembic.ini'))
        config.set_main_option('script_location', str(SOURCE / 'migrations'))
        config.set_main_option('sqlalchemy.url', url)
        command.upgrade(config, 'head')
        engine = create_engine(url)
        with engine.begin() as connection:
            connection.exec_driver_sql("CREATE ROLE b0_queue_eval LOGIN PASSWORD '" + password + "' NOSUPERUSER NOBYPASSRLS")
            connection.execute(text('GRANT agent_memory_app TO b0_queue_eval'))
            fingerprint = {'postgres': connection.scalar(text('SELECT version()')),
                'non_owner_superuser': connection.scalar(text("SELECT rolsuper FROM pg_roles WHERE rolname='b0_queue_eval'")),
                'non_owner_bypassrls': connection.scalar(text("SELECT rolbypassrls FROM pg_roles WHERE rolname='b0_queue_eval'")),
                'container_image_id': pg.get_wrapped_container().image.id}
        engine.dispose()
        assert not fingerprint['non_owner_superuser'] and not fingerprint['non_owner_bypassrls']
        appurl = make_url(url).set(drivername='postgresql+psycopg_async', username='b0_queue_eval', password=password).render_as_string(hide_password=False)
        observations = asyncio.run(exercise(appurl))
    stale = [r for r in observations if r['scenario'] == 'expired_owner']
    failures = [r for r in observations if r['status'] != 'succeeded']
    report = {'created_at': datetime.now(timezone.utc).isoformat(), 'baseline_commit': commit,
        'harness_script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'method': 'Frozen PostgresJobQueue, actual new disposable PostgreSQL with non-owner/non-bypass role, three repeats, real database-clock expiry/backoff; no SQL state/time edits and no models',
        'data_level': 'C synthetic queue controls, not real model/worker-process fault injection or PF',
        'environment': fingerprint, 'observations': observations,
        'RL3': {'status': 'partial measured: real queue persistence, no candidate-commit transaction race yet',
            'stale_mutation_success_count': sum(r['stale_actions_attempted'] - r['stale_actions_rejected'] for r in stale),
            'stale_mutation_attempts': sum(r['stale_actions_attempted'] for r in stale), 'repeats': len(stale),
            'ci95': None, 'ci_reason': 'fixed fixture count, not population failure probability'},
        'RL4': {'status': 'partial queue fault controls only; not model outage/process crash or full-pipeline recovery',
            'total_tasks': len(observations), 'succeeded': len(observations) - len(failures), 'dead': len(failures),
            'all_tasks_success_fraction': (len(observations) - len(failures)) / len(observations),
            'all_tasks_denominator_includes_injected_permanent_and_exhausted_failures': True,
            'attempts_distribution': dict(Counter(r['attempts'] for r in observations)),
            'ci95': None, 'ci_reason': 'finite prescribed scenario matrix; empirical repeats separately, not IID deployment tasks'},
        'phase2_accepted': False, 'stage3_started': False, 'model_calls': 0}
    PUBLIC.mkdir(parents=True, exist_ok=True)
    (PUBLIC / 'queue-controls.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'RL3': report['RL3'], 'RL4': report['RL4'], 'model_calls': 0}, ensure_ascii=False))


if __name__ == '__main__':
    main()
