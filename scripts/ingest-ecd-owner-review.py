"""Immutable ECD owner confirmation intake. Raw content remains server-local."""
import csv,json
from collections import Counter
from pathlib import Path
from agent_memory.evals.evidence_v3 import sha
ROOT=Path('.local/phase1/round3/temporal-v1/ecd-owner')
SUBMITTED=Path('.local/ecd120-human-labeled.csv')
TEMPLATE=Path('.local/phase1/round3/reviews/ecd-manual-120.csv')

def rows(p):
 with p.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))

def main():
 original=rows(TEMPLATE);submitted=rows(SUBMITTED)
 before={r['conversation_id']:r for r in original};after={r['conversation_id']:r for r in submitted}
 if len(before)!=len(original) or len(after)!=len(submitted) or before.keys()!=after.keys():raise ValueError('review ID coverage changed')
 classified=[];counts=Counter()
 for key,row in after.items():
  if row.keys()!=before[key].keys():raise ValueError('column set changed')
  for field in row:
   if not field.startswith('human_') and row[field]!=before[key][field]:raise ValueError('frozen source field changed')
  memories=row['human_memories'].strip();negative=row['human_no_memories'].strip().lower()
  if negative not in ('','true','false'):raise ValueError('invalid negative boolean')
  if memories and negative=='true':raise ValueError('contradictory owner answers')
  label='positive' if memories else ('negative' if negative=='true' else 'uncertain')
  counts[label]+=1;classified.append({**row,'classification':label})
 protected=json.loads(Path('.local/phase1/round3/followup/protected-hashes.json').read_text())
 for path,h in protected.items():
  if sha(Path(path))!=h:raise ValueError('protected old review changed')
 ROOT.mkdir(parents=True,exist_ok=False,mode=0o700)
 for label in ('positive','negative','uncertain'):
  (ROOT/f'{label}-private.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in classified if r['classification']==label))
 report={'source':'ECD120','annotation_method':'AI 草稿加人工确认','independent_human_annotation':False,
  'agent_modified_owner_labels':False,'conversations':len(submitted),'counts':dict(counts),
  'negative_fraction_all_conversations':counts['negative']/len(submitted),'negative_fraction_denominator':len(submitted),
  'uncertain_excluded_from_positive_and_negative':True,'negative_gold_conversations':counts['negative'],
  'positive_conversations_not_memory_point_count':counts['positive'],'uncertain_conversations':counts['uncertain'],
  'raw_private_only':True,'license':'unclear; no source or memory text in GitHub/public materials',
  'owner_message_id':'om_x100b62ae68e1b0a0c3059bdbc44bdbc','submitted_sha256':sha(SUBMITTED),'template_sha256':sha(TEMPLATE),
  'all_frozen_fields_match':True,'protected_original_files_unchanged':True,
  'scope_note':'Negative small gold for these reviewed conversations; stratified sample, not an estimate of full ECD prevalence. Seven positive conversations do not automatically add seven memory points to DuLeMon gold. No system false-extraction rate has been measured in this intake.'}
 (ROOT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps(report,ensure_ascii=False))
if __name__=='__main__':main()
