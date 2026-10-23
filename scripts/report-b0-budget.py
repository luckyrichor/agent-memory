"""Use real pilot usage to document full-dev versus sampled workload estimates."""
import json,math
from pathlib import Path

ROOT=Path('.local/phase2/b0')
def main():
 manifest=json.loads(Path('docs/baselines/b0/datasets-v1.json').read_text())
 pilot=json.loads((ROOT/'runtime-pilot-v1/summary.json').read_text())
 units={r['role']:r for r in pilot['records'] if r.get('http')==200}
 estimates={}
 for name,row in manifest.items():
  docs=row['dev_documents'];q=row['dev_questions'];repeats=3;groups=4;modes=2
  extraction=docs*repeats;embeddings=(docs*2+q*2)*repeats;answers=q*groups*modes*repeats
  estimates[name]={'dev_documents':docs,'dev_questions':q,'extraction_calls_estimate':extraction,'embedding_calls_estimate':embeddings,'answer_calls_estimate':answers,'judge_calls_estimate':answers,'combined_calls_estimate':extraction+embeddings+answers*2,
  'extraction_tokens_estimate':extraction*units['extraction']['usage']['total_tokens'],
  'embedding_tokens_estimate':embeddings*units['embedding']['usage']['total_tokens'],
  'answer_tokens_no_memory_lower_context_estimate':answers*units['answer']['usage']['total_tokens']}
 result={'pilot':pilot,'full_dev_estimates':estimates,'assumptions':['Document counts are a lower bound before 4000-character bounded import chunks','Full-chain extracted memory count unknown; embedding estimate assumes one output memory per input document; it is not a claimed production yield','Answer estimate uses real no-memory pilot and underestimates full-context inputs; long histories separately dominate tokens','No invented judge token observations: pre-run 1100 tokens/call is plan assumption until real grading','Counts include 3 fresh extraction/answer/judge repeats; cached replay is not an independent repeat','Actual call ledger supersedes estimates; runtime quota pauses and cannot auto-rotate models'],
 'measured_pilot_calls':pilot['calls'],'decision':'use transparently sampled dev conversations and stratified questions for functional measurement; full dev S alone has large input workload; preserve all history of each selected conversation; test excluded','not_quality_evidence':True}
 Path('docs/baselines/b0/workload-estimate-v1.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps({k:v['combined_calls_estimate'] for k,v in estimates.items()}))
if __name__=='__main__':main()
