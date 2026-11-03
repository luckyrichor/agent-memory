"""Scripted pre-run evidence for the strict new B0; never contains raw conversations."""
import hashlib,json,re,subprocess
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path

def main():
 root=Path('.local/phase2/b0/frozen-deepseek-20261026-v1');run=root/'pilot-run';out=Path('docs/reports/phase2-b0-rebuild-2026-10-26');usage=[json.loads(x) for x in (run/'usage.jsonl').read_text().splitlines()];rows=json.loads((run/'graded-results-private.json').read_text());imports=[json.loads(x) for x in (run/'imports-private.jsonl').read_text().splitlines()]
 assert len(rows)==24 and all(r['answer_model']=='deepseek-v4-pro' for r in rows if r['answer_valid'])
 assert all(r['provider'] in ('DeepSeek','TokenHub') and not r.get('cache_hit') for r in usage)
 roles={}
 for role in sorted({r['role'] for r in usage}):
  subset=[r for r in usage if r['role']==role];known=[r for r in subset if r.get('usage')];roles[role]={'calls':len(subset),'reported_total_tokens':sum(r['usage'].get('total_tokens',0) for r in known),'unknown_usage':len(subset)-len(known),'http_counts':dict(Counter(str(r.get('http')) for r in subset))}
 proofs={}
 for name in ('deepseek-preflight','judge-preflight','judge-minimax-preflight-v2','vector-native','extraction-native','answer-native','judge-native','cross-reference-native'):
  p=root/name/'summary.json';d=json.loads(p.read_text());assert d['passed'];proofs[name]={'summary':d,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
 report={'at':datetime.now(timezone.utc).isoformat(),'pilot_status':json.loads((run/'status.json').read_text()),'pilot_answer_rows':len(rows),'pilot_valid_answers':sum(r['answer_valid'] for r in rows),'pilot_valid_grades':sum(type(r['judge_correct']) is bool for r in rows),'actual_calls':len(usage),'roles':roles,'answer_models':dict(Counter(r['answer_model'] for r in rows)),'judge_models':dict(Counter(r['judge_model'] for r in rows)),'vector_models':sorted({r['model'] for r in usage if r['role']=='embedding'}),'providers':sorted({r['provider'] for r in usage}),'old_vector_replays':sum(r.get('cache_hit',False) for r in usage),'index_rebuild_observations':[{k:r.get(k) for k in ('mode','repeat','memories','unique_memory_versions','stored_current_model_vectors','vector_index_rebuilt','memory_status_counts','evidence_mapping_present')} for r in imports],'sample_choice':'same previously frozen seeded development sample; pilot measured calls and protocol, never selects favorable scores','single_model_freeze_request_and_observed_id':'deepseek-v4-pro','preflight_proofs':proofs,'source_hashes':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [run/'run-manifest.json',run/'usage.jsonl',run/'graded-results-private.json']}}
 (out/'preflight-and-pilot.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
 log=root/'check-final-source-separation.log';text=log.read_text();n,t=re.search(r'(\d+) passed in ([\d.]+)s',text).groups();verify={'at':report['at'],'repository_base_commit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'working_tree_uncommitted':True,'pytest_passed':int(n),'pytest_seconds':float(t),'ruff_passed':'All checks passed!' in text,'strict_mypy_passed':'Success: no issues found' in text,'foundation_passed':'failed=0' in text,'log_sha256':hashlib.sha256(log.read_bytes()).hexdigest(),'regressions':['Ark blocked before network','alternate DeepSeek model not allowed','response version drift stops','vector budget prevents extra HTTP','prior mixed tables cannot be adopted','native Tencent fixed1024 request and genuine index rebuild observations']}
 (out/'verification.json').write_text(json.dumps(verify,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps({'pilot_rows':len(rows),'valid_grades':report['pilot_valid_grades'],'roles':roles,'index_rebuild':report['index_rebuild_observations'],'release_tests':n},ensure_ascii=False))
if __name__=='__main__':main()
