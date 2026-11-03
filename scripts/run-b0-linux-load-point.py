"""One bounded Linux open-loop run with a concurrent independent host monitor.

Target is never defaulted: pass --base-url/--host or export B0_BASE_URL/B0_HOST.
Example: B0_BASE_URL=https://<host> B0_HOST=<host> python run-b0-linux-load-point.py --label tx2-10k --repeat 1
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--label', choices=['tx2-10k','tx2-100k','tx2-write-10k','tx2-write-100k','tx2-context-10k','tx2-context-100k','stair2-search-01','stair2-search-025','stair2-search-05','stair2-context-01','stair2-context-025','stair2-context-05','stair-search-01','stair-search-025','stair-search-05','stair-context-01','stair-context-025','stair-context-05'], required=True)
    parser.add_argument('--repeat', type=int, choices=[1,2,3], required=True)
    parser.add_argument('--rate', type=float, choices=[0.1,0.25,0.5,1], default=1)
    parser.add_argument('--base-url', default=os.environ.get('B0_BASE_URL'), help='target base URL; required (env B0_BASE_URL)')
    parser.add_argument('--host', default=os.environ.get('B0_HOST'), help='target Host header; required (env B0_HOST)')
    args = parser.parse_args()
    base_url = (args.base_url or '').strip()
    host = (args.host or '').strip()
    missing = [name for name, value in (('B0_BASE_URL/--base-url', base_url), ('B0_HOST/--host', host)) if not value]
    if missing:
        parser.error('missing required target: ' + ', '.join(missing) + '; export B0_BASE_URL/B0_HOST or pass --base-url/--host')
    root = Path.home()/'project/agent-memory-b0-load-private'
    output = root/'.local'/args.label
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    name = f'run-{args.repeat}'
    if (output/(name+'-summary.json')).exists():
        raise RuntimeError('EXISTING_POINT_EVIDENCE_MUST_NOT_BE_OVERWRITTEN')
    env = dict(os.environ, B0_BASE_URL=base_url, B0_HOST=host, B0_RATE=str(args.rate),
               B0_REQUESTS_PATH=str(root/('requests-write-private.json' if '-write-' in args.label else 'requests-context-private.json' if 'context-' in args.label else 'requests-private.json')), NO_PROXY='*', no_proxy='*')
    with (output/(name+'.log')).open('x') as log:
        process = subprocess.Popen([str(root/'bin/k6'),'run','--no-usage-report',
            '--log-format=json','--summary-export',str(output/(name+'-summary.json')),str(root/'b0-open-loop.js')],
            env=env, stdout=log, stderr=log)
        monitor = subprocess.Popen([sys.executable,str(root/'b0-load-monitor.py'),
            '--pid',str(process.pid),'--seconds','400','--output',str(output/(name+'-resources.json'))],
            stdout=subprocess.DEVNULL,stderr=log)
        try:
            code = process.wait(timeout=420)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:process.wait(timeout=10)
            except subprocess.TimeoutExpired:process.kill();process.wait()
            code = 124
        monitor_code = monitor.wait(timeout=410)
    resources_path = output/(name+'-resources.json')
    resource_valid = monitor_code == 0 and resources_path.exists() and not json.loads(resources_path.read_text())['invalid']
    result = {'label':args.label,'repeat':args.repeat,'k6_exit':code,
              'load_host_resources_valid':resource_valid,'monitor_exit':monitor_code,
              'summary_collected':(output/(name+'-summary.json')).exists()}
    (output/(name+'-status.json')).write_text(json.dumps(result)+'\n')
    print(json.dumps(result),flush=True)


if __name__ == '__main__':
    main()
