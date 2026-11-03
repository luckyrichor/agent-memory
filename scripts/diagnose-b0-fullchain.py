"""Read-only attribution of exploratory full-chain zeros; never edits frozen runtime."""
import argparse,hashlib,json
from collections import Counter,defaultdict
from pathlib import Path
from agent_memory.evals.b0_frozen import BIAS

def records(path):
 if not path.exists():return []
 with path.open() as f:return [json.loads(s) for s in f if s.strip()]
def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
def origin(root,key,seen=None):
 seen=set() if seen is None else seen
 root=root.resolve()
 if root in seen:return None
 seen.add(root);dataset,cid,mode,repeat=key;p=root/'mappings'/(digest(list(key))+'.json')
 if p.exists():return p
 for r in records(root/'resumed-conversations.jsonl'):
  if (r['dataset'],r['conversation_id'],r['mode'],r['repeat'])==key:
   found=origin(Path(r['from_run']),key,seen)
   if found:return found
 for r in records(root/'resumed-datasets.jsonl'):
  if r['dataset']==dataset:
   found=origin(Path(r['from_run']),key,seen)
   if found:return found
 return None

def main():
 p=argparse.ArgumentParser();p.add_argument('--input',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
 imports=records(a.input/'imports-private.jsonl');graded=json.loads((a.input/'graded-results-private.json').read_text());stats=defaultdict(Counter);private=[];mapping_references=[]
 for row in imports:
  if row['mode']!='full':continue
  key=(row['dataset'],row['conversation_id'],row['mode'],row['repeat']);path=origin(a.input,key);mapping=json.loads(path.read_text()) if path else []
  memories=row['memories'];active=row['active_memories'];present=sum(bool(m.get('version_id') and m.get('source_id') and m.get('session_id')) for m in mapping)
  failures=[x for x in row['extraction_outcomes'] if x['outcome']!='no_job'];failed=sum(x.get('extractor_last_failure')!='NONE' for x in failures)
  matched=[r for r in graded if (r['dataset'],r['conversation_id'],r['mode'],r['repeat'])==key and r['system']=='system'];hits=sum(bool(r['ranked_evidence_sets']) for r in matched);rt=[r for r in matched if r.get('retrieval')]
  reason='extraction_no_output' if memories==0 else ('evidence_mapping_missing' if present<memories else ('filtered_nonactive' if active==0 else ('retrieval_no_recall' if not hits else 'nonzero_return')))
  item={'dataset':row['dataset'],'conversation_id_digest':digest(row['conversation_id']),'repeat':row['repeat'],'source_chunks':row['chunks'],'extracted_memory_rows':memories,'active_memory_rows':active,'mapped_memory_rows':present,'mapping_file_found':path is not None,'extraction_jobs':len(failures),'extraction_failure_or_fallback_jobs':failed,'system_question_rows':len(matched),'questions_with_returned_evidence':hits,'rt_observations':len(rt),'rt1_at10_numerator':sum(float(r['retrieval']['10'].get('RT1',0)) for r in rt),'primary_attribution':reason,'memory_status_counts':dict(Counter(m.get('memory_status','unknown') for m in mapping))}
  private.append(item);s=stats[row['dataset']]
  for field in ('source_chunks','extracted_memory_rows','active_memory_rows','mapped_memory_rows','extraction_jobs','extraction_failure_or_fallback_jobs','system_question_rows','questions_with_returned_evidence','rt_observations','rt1_at10_numerator'):s[field]+=item[field]
  s['conversation_mode_repeat_units']+=1;s['cause/'+reason]+=1
  if path:mapping_references.append({'path_sha256':digest(str(path.relative_to(Path.cwd()))),'file_sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
 report={'scope':'prior exploratory data, not new B0; development only; no API calls','datasets':{name:dict(v) for name,v in stats.items()},'conversation_observations':private,'mapping_proof_hashes':mapping_references,'source':{'imports_sha256':hashlib.sha256((a.input/'imports-private.jsonl').read_bytes()).hexdigest(),'graded_results_sha256':hashlib.sha256((a.input/'graded-results-private.json').read_bytes()).hexdigest()},'code_evidence':{'retrieval':'source-B0/src/agent_memory/infrastructure/retrieval.py:base_filters requires m.status==active','extraction':'source-B0 extraction worker persists candidate/unverified output; harness does not promote','runtime_not_changed':True},'planned_new_B0_limitation':BIAS,'interpretation':'no output, missing evidence mapping, lifecycle filtering and retrieval failure are distinct; candidate-only mapped output is filtered by design, not automatically an extractor failure or a vector recall defect'}
 a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'datasets':report['datasets'],'units':len(private)},ensure_ascii=False))
if __name__=='__main__':main()
