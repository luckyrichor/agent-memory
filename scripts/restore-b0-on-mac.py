"""Restore a fictional-only B0 dump into a dedicated local Mac cluster."""
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import time

import psycopg
from psycopg import sql


def main():
    root = Path.home() / 'project/agent-memory-b0-private'
    expected = json.loads((root/'backup100k-summary.json').read_text())
    dump = root/'b0-100k.dump'
    with dump.open('rb') as stream:
        actual_hash = hashlib.file_digest(stream, 'sha256').hexdigest()
    if dump.stat().st_size != expected['bytes'] or actual_hash != expected['sha256']:
        raise RuntimeError('TRANSFERRED_BACKUP_HASH_OR_SIZE_MISMATCH')
    pg = Path('/opt/homebrew/opt/postgresql@16/bin')
    data = root / 'pgdata'
    socket = root / 'pgsocket'
    socket.mkdir(exist_ok=True, mode=0o700)
    config_path = root / 'restore-config-private.json'
    if not config_path.exists():
        password = secrets.token_hex(24)
        config = {'root_password': password, 'app_password': secrets.token_hex(24)}
        config_path.write_text(json.dumps(config) + '\n')
        config_path.chmod(0o600)
    config = json.loads(config_path.read_text())
    pwfile = root / 'pg-root-password-private.txt'
    pwfile.write_text(config['root_password'] + '\n')
    pwfile.chmod(0o600)
    if not data.exists():
        subprocess.run([str(pg/'initdb'), '-D', str(data), '-U', 'agent_memory',
                        '--auth-local=trust', '--auth-host=scram-sha-256',
                        '--pwfile='+str(pwfile)], check=True, stdout=subprocess.DEVNULL)
    if subprocess.run([str(pg/'pg_ctl'), '-D', str(data), 'status'],
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
        subprocess.run([str(pg/'pg_ctl'), '-D', str(data), '-l', str(root/'postgres.log'),
                        '-o', f'-h 127.0.0.1 -p 65432 -k {socket}', 'start'],
                       check=True, stdout=subprocess.DEVNULL)
    root_dsn = f"host=127.0.0.1 port=65432 user=agent_memory password={config['root_password']} dbname=postgres"
    name = 'b0pf_restored_100000_100'
    roles = json.loads((root/'roles-private.json').read_text())
    with psycopg.connect(root_dsn, autocommit=True) as connection:
        if connection.execute('SELECT 1 FROM pg_database WHERE datname=%s', (name,)).fetchone():
            raise RuntimeError('RESTORED_DATABASE_ALREADY_EXISTS_DO_NOT_OVERWRITE')
        for role in roles['roles']:
            identifier = sql.Identifier(role['name'])
            if role['name'] != 'agent_memory':
                connection.execute(sql.SQL('CREATE ROLE {}').format(identifier))
            flags = ' '.join(('' if role[k] else 'NO')+keyword for k, keyword in
                             [('superuser','SUPERUSER'), ('bypassrls','BYPASSRLS'),
                              ('inherit','INHERIT'), ('login','LOGIN')])
            connection.execute(sql.SQL('ALTER ROLE {} '+flags).format(identifier))
        for membership in roles['memberships']:
            connection.execute(sql.SQL('GRANT {} TO {}').format(
                sql.Identifier(membership[0]), sql.Identifier(membership[1])))
        connection.execute(sql.SQL('ALTER ROLE b0_pf_app PASSWORD {}').format(sql.Literal(config['app_password'])))
        connection.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
    started = time.monotonic()
    env = dict(os.environ, PGPASSWORD=config['root_password'])
    with (root/'restore-errors-private.log').open('w') as errors:
        subprocess.run([str(pg/'pg_restore'), '--exit-on-error', '-h','127.0.0.1','-p','65432',
                        '-U','agent_memory','-d',name, str(root/'b0-100k.dump')],
                       env=env, check=True, stdout=subprocess.DEVNULL, stderr=errors)
    target = {'database_url': f"postgresql+psycopg://b0_pf_app:{config['app_password']}@127.0.0.1:65432/{name}",
              'root_dsn': root_dsn.replace('dbname=postgres', 'dbname='+name)}
    target_path = root/'target-config-private.json'
    target_path.write_text(json.dumps(target)+'\n'); target_path.chmod(0o600)
    report = {'restore_seconds': time.monotonic()-started, 'database': name,
              'dump_bytes': (root/'b0-100k.dump').stat().st_size,
              'dump_sha256': hashlib.file_digest((root/'b0-100k.dump').open('rb'), 'sha256').hexdigest(),
              'synthetic_only': True}
    (root/'restore-summary.json').write_text(json.dumps(report)+'\n')
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
