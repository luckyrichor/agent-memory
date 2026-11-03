"""Bounded stage2 continuation: no new budget approval, no stage3, no publication."""
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
STATE=ROOT/'.local/phase2/b0/expansion-20261101'

def record(value):
    p=STATE/'continuation-private.json';p.write_text(json.dumps(value,indent=2)+'\n');p.chmod(0o600)

def main():
    unit='agent-memory-b0-rate-staircase-v2-20261101.service'
    record({'status':'waiting_for_staircase','unit':unit,'next':'PerLTQA300 within original remaining vector cap','stage3_started':False})
    deadline=time.monotonic()+11000
    while time.monotonic()<deadline:
        checkpoint=STATE/'staircase-private.json'
        if checkpoint.exists():
            value=json.loads(checkpoint.read_text())
            if value['status']!='running':break
        active=subprocess.run(['systemctl','--user','is-active','--quiet',unit]).returncode==0
        if not active:
            record({'status':'paused_staircase_interrupted','stage3_started':False});return
        time.sleep(10)
    else:
        record({'status':'paused_staircase_wait_timeout','stage3_started':False});return
    if value['status']!='measurements_complete' or len(value['points'])!=18:
        record({'status':'paused_staircase_requires_review','staircase_status':value['status'],'completed_points':len(value['points']),'stage3_started':False});return
    # Avoid additional model activity while load measurement is running.
    source=ROOT/'.local/phase2/b0/source-B0'
    assert not subprocess.check_output(['git','status','--porcelain'],cwd=source,text=True)
    output=STATE/'perltqa300-run'
    if output.exists():
        record({'status':'paused_existing_quality_evidence_no_overwrite','stage3_started':False});return
    ledger=json.loads((STATE/'budget-ledger.json').read_text())
    assert ledger['prior_frozen_lineage_attempts']+ledger['new_perltqa_reserved_max_attempts']<=ledger['original_total_cap']
    record({'status':'running_perltqa300','maximum_new_vector_attempts':24990,'question_target':300,'stage3_started':False})
    command=[sys.executable,'scripts/run-b0.py','--dataset','perltqa_zh','--mode','both','--config',str(STATE/'config-perltqa300-private.json'),'--metrics','EX,LC,RT,CX,E,RL,SC','--fixed-judge','glm-5.2','--output',str(output)]
    with (STATE/'perltqa300-control-private.log').open('x') as log:
        try:result=subprocess.run(command,cwd=ROOT,stdout=log,stderr=log,timeout=64800)
        except subprocess.TimeoutExpired:
            record({'status':'paused_quality_timeout','stage3_started':False});return
    status=json.loads((output/'status.json').read_text()) if (output/'status.json').exists() else {'status':'no_status'}
    record({'status':'quality_execution_ended_requires_review','control_exit':result.returncode,'quality_status':status,'other_datasets':'pending budget decision; LoCoMo pending dev-data decision','stage3_started':False})
    if (output/'run-manifest.json').exists() and (output/'status.json').exists():
        subprocess.run([sys.executable,'scripts/summarize-b0.py','--input',str(output),'--output',str(output/'aggregate')],cwd=ROOT,check=True)
    # Human calibration/aggregation must be reviewed; no automatic stage3 or incomplete file send.

if __name__=='__main__':main()
