"""Supervise bounded independent-host capacity points; never publish or accept phase2."""
import json
from pathlib import Path
import subprocess
import sys
import time

import psycopg

ROOT = Path(__file__).resolve().parents[1]
CAP = ROOT/'.local/phase2/b0/completion-20261028/capacity'
REMOTE = 'project/agent-memory-b0-load-private'


def stop_owned_app(unit, database):
    subprocess.run(['systemctl','--user','kill','--signal=SIGTERM',unit],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    config = json.loads((CAP/'database-config-private.json').read_text())
    with psycopg.connect(config['root_dsn'],autocommit=True) as c:
        c.execute("SELECT pg_cancel_backend(pid) FROM pg_stat_activity WHERE datname=%s AND usename='b0_pf_app' AND state='active'",(database,))
    try:
        subprocess.run(['systemctl','--user','stop',unit],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=20)
    except subprocess.TimeoutExpired:
        subprocess.run(['systemctl','--user','kill','--signal=SIGKILL',unit],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    # Remaining sessions belong only to this isolated fixture's app role.
    with psycopg.connect(config['root_dsn'],autocommit=True) as c:
        c.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=%s AND usename='b0_pf_app'",(database,))


def main():
    checkpoint = CAP/'tx2-sequence-private.json'
    if checkpoint.exists():
        raise RuntimeError('EXISTING_SEQUENCE_MUST_BE_REVIEWED_BEFORE_RESUME')
    state = {'status':'running','points':[],'external_model_calls':0}
    current_unit = None; current_database = None; monitor = None
    try:
        for size in [10000,100000]:
            label = 'tx2-10k' if size == 10000 else 'tx2-100k'
            database = f'b0pf_seed_{size}_100'
            for repeat in [1,2,3]:
                name = f'{label}-r{repeat}'
                unit = 'agent-memory-'+name+'-20261030'
                current_unit,current_database = unit,database
                server_log = CAP/(name+'-http-private.jsonl')
                with (CAP/(name+'-app-private.log')).open('x') as log:
                    subprocess.run(['systemd-run','--user','--unit='+unit,'--property=WorkingDirectory='+str(ROOT),
                        '--property=StandardOutput=append:'+str(CAP/(name+'-app-private.log')),
                        '--property=StandardError=append:'+str(CAP/(name+'-app-private.log')),
                        str(ROOT/'.venv/bin/python'),'scripts/b0-capacity-app.py','--config',
                        str(CAP/(database+'-private.json')),'--log',str(server_log)],check=True,stdout=log,stderr=log)
                time.sleep(3)
                monitor = subprocess.Popen([sys.executable,str(ROOT/'scripts/monitor-b0-server.py'),
                    '--seconds','410','--output',str(CAP/(name+'-server-private.jsonl'))],
                    stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                start = time.monotonic()
                with (CAP/(name+'-control-private.log')).open('x') as log:
                    remote = subprocess.run(['ssh','-T','-o','BatchMode=yes','-o','ConnectTimeout=10',
                        '-o','ServerAliveInterval=15','-o','ServerAliveCountMax=4','tx2',
                        f'python3 ~/{REMOTE}/run-b0-linux-load-point.py --label {label} --repeat {repeat}'],
                        stdout=log,stderr=log,timeout=500)
                monitor_code = monitor.wait(timeout=30)
                stop_owned_app(unit+'.service',database)
                destination = CAP/name;destination.mkdir(mode=0o700)
                subprocess.run(['scp',f'tx2:{REMOTE}/.local/{label}/run-{repeat}-summary.json',
                    f'tx2:{REMOTE}/.local/{label}/run-{repeat}-resources.json',
                    f'tx2:{REMOTE}/.local/{label}/run-{repeat}-status.json',str(destination)],check=True,timeout=45)
                summary = json.loads((destination/f'run-{repeat}-summary.json').read_text())
                resources = json.loads((destination/f'run-{repeat}-resources.json').read_text())
                metrics = summary['metrics']
                point = {'size':size,'repeat':repeat,'control_exit':remote.returncode,'server_monitor_exit':monitor_code,
                    'load_host_resources_valid':not resources['invalid'],
                    'maximum_load_cpu_fraction':max(s['host_cpu_fraction'] or 0 for s in resources['samples']),
                    'maximum_load_memory_fraction':max(s['host_memory_fraction'] for s in resources['samples']),
                    'measured_metrics':{k:metrics.get(k) for k in ['b0_sample_requests','b0_sample_errors','b0_sample_client_ms','b0_sample_server_ms','dropped_iterations']},
                    'wall_seconds':time.monotonic()-start,'rate_per_second':1,'warmup_seconds':60,'measurement_seconds':300}
                state['points'].append(point);checkpoint.write_text(json.dumps(state,indent=2)+'\n');checkpoint.chmod(0o600)
                print(json.dumps(point),flush=True)
                if resources['invalid']:
                    state['status']='stopped_invalid_load_host_resources'
                    break
            if state['status'] != 'running':break
        if state['status']=='running':state['status']='measurements_complete'
    except Exception as exc:
        state['status']='failed_requires_review';state['failure_class']=type(exc).__name__
        raise
    finally:
        if monitor is not None and monitor.poll() is None:
            monitor.terminate()
            try:monitor.wait(timeout=5)
            except subprocess.TimeoutExpired:monitor.kill();monitor.wait()
        if current_unit:
            stop_owned_app(current_unit+'.service',current_database)
        checkpoint.write_text(json.dumps(state,indent=2)+'\n');checkpoint.chmod(0o600)
        report = {**state,'phase2_accepted':False,'full_aggregate_ready':False,
            'environment':{'load_host':'TX2 VM-4-5-ubuntu,2CPU/2GB','target':'TX isolated B0 PostgreSQL container,2CPU/3GiB/shm512MiB',
                           'model':'kinfra-text-embedding-0.6b native1024,precomputed exact real vectors','query_count':128,
                           'corpus':'fixed fictional32-character query set sampled from first10k seed IDs and reused at both scales; no real conversations exported',
                           'repeats':'fresh API process and drained app database sessions before each timed run; database cache not reset'},
            'limitation':'Only read/search1QPS points at10k/100k,100tenants,80%hot tenant. Not write/context throughput, full tenant-count grid, maximum capacity or cross-region proof. Failed/dropped requests retained. Load host invalidity forbids capacity claims.'}
        (ROOT/'docs/reports/phase2-b0-completion-2026-10-28/tx2-public-load.json').write_text(json.dumps(report,indent=2)+'\n')
        subprocess.run(['sudo','-n','rm','-f','/etc/nginx/sites-enabled/zz-agent-memory-b0-pf-20261028'],check=True)
        subprocess.run(['sudo','-n','nginx','-t'],check=True)
        subprocess.run(['sudo','-n','systemctl','reload','nginx'],check=True)
        subprocess.run([sys.executable,str(ROOT/'scripts/report-b0-completion.py'),'--record-handoff'],check=True)


if __name__ == '__main__':
    main()
