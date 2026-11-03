"""Three open-loop runs with actual Mac resource sampling; private inputs only.

Target is never defaulted: pass --base-url/--host or export B0_BASE_URL/B0_HOST.
Example: B0_BASE_URL=https://<host> B0_HOST=<host> python run-b0-mac-load.py --label load10k-20261029
"""
import json
import argparse
import os
from pathlib import Path
import subprocess
import time

import psutil


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--label', choices=['load10k-20261029','load100k-20261029'], default='load10k-20261029')
    parser.add_argument('--base-url', default=os.environ.get('B0_BASE_URL'), help='target base URL; required (env B0_BASE_URL)')
    parser.add_argument('--host', default=os.environ.get('B0_HOST'), help='target Host header; required (env B0_HOST)')
    args = parser.parse_args()
    base_url = (args.base_url or '').strip()
    host = (args.host or '').strip()
    missing = [name for name, value in (('B0_BASE_URL/--base-url', base_url), ('B0_HOST/--host', host)) if not value]
    if missing:
        parser.error('missing required target: ' + ', '.join(missing) + '; export B0_BASE_URL/B0_HOST or pass --base-url/--host')
    root = Path.home()/'project/agent-memory-b0-private'
    output = root/args.label
    output.mkdir(mode=0o700)
    env = dict(os.environ, B0_BASE_URL=base_url, B0_HOST=host, B0_RATE='1',
               B0_REQUESTS_PATH=str(root/'load10k-requests-private.json'),
               NO_PROXY='*', no_proxy='*')
    summary = []
    for repeat in range(1,4):
        with (output/f'run-{repeat}.log').open('w') as log:
            proc = subprocess.Popen(['/opt/homebrew/bin/k6','run',
                '--summary-export',str(output/f'run-{repeat}-summary.json'),
                str(root/'b0-open-loop.js')], env=env, stdout=log, stderr=log)
            samples = []; psutil.cpu_percent()
            while proc.poll() is None:
                time.sleep(1)
                samples.append({'at':time.time(), 'host_cpu_percent':psutil.cpu_percent(),
                                'host_memory_percent':psutil.virtual_memory().percent,
                                'disk_io':psutil.disk_io_counters()._asdict()})
        invalid = any(s['host_cpu_percent']>70 or s['host_memory_percent']>70 for s in samples)
        report = {'repeat':repeat,'exit':proc.returncode,'resource_invalid':invalid,'samples':samples}
        (output/f'run-{repeat}-resources.json').write_text(json.dumps(report)+'\n')
        summary.append({k:report[k] for k in ('repeat','exit','resource_invalid')})
        print(json.dumps(summary[-1]),flush=True)
    (output/'runs.json').write_text(json.dumps(summary)+'\n')


if __name__ == '__main__':
    main()
