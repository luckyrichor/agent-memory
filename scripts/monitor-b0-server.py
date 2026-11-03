"""One-second server resource sampling alongside a declared capacity run."""
import json
import argparse
from pathlib import Path
import subprocess
import time

import psycopg

ROOT = Path(__file__).resolve().parents[1]
CAP = ROOT/'.local/phase2/b0/completion-20261028/capacity'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--seconds', type=int, default=1200)
    parser.add_argument('--output', type=Path, default=CAP/'pf-server-resources-private.jsonl')
    args = parser.parse_args()
    if args.seconds < 1 or CAP.resolve() not in args.output.resolve().parents:
        parser.error('bounded duration and private capacity output required')
    config = json.loads((CAP/'database-config-private.json').read_text())
    pid = subprocess.check_output(['docker','inspect','--format','{{.State.Pid}}','agent-memory-b0-capacity-20261028'],text=True).strip()
    group = Path('/proc')/pid/'cgroup'
    relative = group.read_text().split('::',1)[1].strip()
    cgroup = Path('/sys/fs/cgroup')/relative.lstrip('/')
    previous = None
    with args.output.open('x') as output:
        for _ in range(args.seconds):
            start = time.monotonic()
            cpu = list(map(int,Path('/proc/stat').read_text().splitlines()[0].split()[1:]))
            mem = {s.split(':')[0]:int(s.split()[1]) for s in Path('/proc/meminfo').read_text().splitlines() if s.startswith(('MemTotal:','MemAvailable:'))}
            row = {'at':time.time(),'cpu_total_ticks':sum(cpu),'cpu_idle_ticks':cpu[3]+cpu[4],
                   'host_memory_fraction':1-mem['MemAvailable']/mem['MemTotal'],
                   'container_memory_bytes':int((cgroup/'memory.current').read_text()),
                   'container_cpu_stat':(cgroup/'cpu.stat').read_text(),
                   'diskstats':Path('/proc/diskstats').read_text()}
            if previous:
                delta = row['cpu_total_ticks']-previous['cpu_total_ticks']
                row['host_cpu_fraction'] = 1-(row['cpu_idle_ticks']-previous['cpu_idle_ticks'])/delta if delta else None
            try:
                with psycopg.connect(config['root_dsn'],connect_timeout=1,application_name='b0_resource_probe') as c:
                    row['database_connections'],row['database_active_connections'] = c.execute("SELECT count(*),count(*) FILTER (WHERE state='active') FROM pg_stat_activity WHERE backend_type='client backend'").fetchone()
            except psycopg.Error:
                row['database_probe_failed'] = True
            row['sampling_seconds'] = time.monotonic()-start
            output.write(json.dumps(row)+'\n');output.flush();previous=row
            time.sleep(max(0,1-(time.monotonic()-start)))


if __name__ == '__main__':
    main()
