"""Archive transient/schema failures before identical-request bounded replay; no quota replay."""
import json,shutil
from datetime import datetime,timezone
from pathlib import Path
from agent_memory.evals.evidence_v3 import sha
ROOT=Path('.local/phase1/round3/temporal-v1/increment-attempt-2')
for p in sorted(ROOT.glob('batch-*/shard-*/**/ledger.json')):
 records=json.loads(p.read_text())
 if not records or records[-1]['status']=='complete':continue
 failed=records[-1]
 if failed.get('quota_blocked'):raise ValueError('quota requires whole-side replacement, not identical model replay')
 if failed.get('error_type') not in ('ConnectError','ReadTimeout','ConnectTimeout','ValidationError','JSONDecodeError'):
  raise ValueError('unexpected failure requires review')
 archive=p.parent/'failed-before-strict-retry'
 archive.mkdir(mode=0o700,exist_ok=False)
 shutil.copy2(p,archive/'ledger.json')
 prefix=f"{failed['offset']:04d}-"
 for src in p.parent.glob(prefix+'*'):
  if src.is_file():shutil.copy2(src,archive/src.name)
 (archive/'amendment.json').write_text(json.dumps({'created_at':datetime.now(timezone.utc).isoformat(),
  'old_ledger_sha256':sha(p),'requested_model':failed['requested_model'],'failed_offset':failed['offset'],
  'failure_type':failed['error_type'],'prompt_sha256':failed['prompt_sha256'],
  'request_sha256':failed['request_sha256'],'scope':'resume identical model/input/prompt after failure; not a model replacement; successful exact-validated results retained; rejected response not used'},indent=2)+'\n')
 p.write_text(json.dumps(records[:-1],indent=2)+'\n')
 print(json.dumps({'stage':str(p.parent),'preserved_successful_items':sum(r['items'] for r in records[:-1]),'retry_offset':failed['offset'],'prior_error':failed['error_type']}))
