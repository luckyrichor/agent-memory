"""Verify the private outgoing CSV against frozen inputs, without publishing content."""
import csv,json,re
from pathlib import Path
from agent_memory.evals.approved_audit import FIELDS
from agent_memory.evals.evidence_v3 import read_rows,sha
from agent_memory.evals.human_review import csv_text,digest
ROOT=Path('.local/phase1/round3/temporal-v1')

def main():
 pointer=json.loads((ROOT/'increment-current.json').read_text());root=Path(pointer['root'])
 result=json.loads((root/'report.json').read_text())
 assert result['complete'] and result.get('audit'),'final independent audit not ready'
 pack=root/'audit72';manifest=json.loads((pack/'manifest.json').read_text())
 for name,value in manifest['files'].items():assert sha(pack/name)==value,'frozen outgoing pack changed'
 for name,value in manifest['inputs'].items():assert sha(Path(name))==value,'frozen outgoing input changed'
 with (pack/'audit-blind.csv').open(encoding='utf-8-sig',newline='') as stream:
  reader=csv.DictReader(stream);assert tuple(reader.fieldnames)==FIELDS;rows=list(reader)
 assert len(rows)==manifest['sample']==72
 blind={r['item_id']:r for r in read_rows(pack/'audit-blind.jsonl')}
 mapping=json.loads((pack/'opaque-map-private.json').read_text())
 assert len({r['item_id'] for r in rows})==len(mapping)==72
 historical={r['item_id'] for r in read_rows(ROOT/'human-all-original.jsonl')}
 split=json.loads(Path('.local/phase1/round3/evidence-v3-replacement/split-private.json').read_text())
 historical.update(split['development']);historical.update(split['final'])
 if (ROOT/'transport-probe-excluded-ids.json').exists():historical.update(json.loads((ROOT/'transport-probe-excluded-ids.json').read_text())['ids'])
 assert not set(mapping.values())&historical,'historical audit/development/final overlap'
 original={r['item_id']:r for r in read_rows(root/'audit-items.jsonl')}
 config=json.loads((root/'manifest.json').read_text());eligible_dialogues=set(config['available_indices'])
 for row in rows:
  assert re.fullmatch('[0-9a-f]{32}',row['item_id'])
  assert row['human_label']==row['human_reason']==''
  expected=blind[row['item_id']];source=original[mapping[row['item_id']]]
  assert row['record_sha256']==digest(expected)
  for field in ('conversation_id','subject','candidate','source'):assert row[field]==csv_text(expected[field])
  assert json.loads(row['source'])==source['source']
  assert row['candidate']==csv_text(source['candidate'])
  assert int(row['conversation_id'].split(':')[-1]) in eligible_dialogues
 report={'csv_sha256':sha(pack/'audit-blind.csv'),'sample':len(rows),'columns':list(FIELDS),
  'blank_human_columns':True,'opaque_ids':True,'source_matches_frozen_original':True,
  'historical_audit_development_final_overlap':0,'new_unused_source_inventory_only':True,
  'audit_seed':manifest['seed'],'annotation_models_by_completed_batch':[{k:r[k] for k in ('batch','models')} for r in result['batches']],
  'gold_adopted':False,'owner_review_pending':result.get('owner_audit_pending',False),'private_preview_only':result.get('audit_prepared_private_only',False),'phase1_accepted':False}
 (root/'outgoing-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps(report,ensure_ascii=False))
if __name__=='__main__':main()
