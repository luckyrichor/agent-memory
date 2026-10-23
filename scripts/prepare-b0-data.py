"""Freeze phase1 references and materialize dev projections only; no model calls."""
import json,hashlib
from collections import Counter
from pathlib import Path
from agent_memory.evals.b0 import development_ids
from agent_memory.evals.datasets import Conversation,file_hash

ROOT=Path('.local/phase2/b0/data-v2')
BASE=Path('.local/phase1/normalized-v3')

def readrows(path):return [json.loads(s) for s in Path(path).open() if s.strip()]
def read(path):return json.loads(Path(path).read_text())

def main():
 ROOT.mkdir(parents=True,exist_ok=False,mode=0o700)
 result={}
 def save(name,conversations,split,inputs,grade):
  dev=development_ids(split);selected=[r for r in conversations if r['conversation_id'] in dev]
  assert len({r['conversation_id'] for r in selected})==len(selected)
  out=ROOT/(name+'-dev.jsonl');out.write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in selected));out.chmod(0o600)
  result[name]={'path':str(out),'sha256':file_hash(out),'inputs_sha256':inputs,'data_level':grade,'full_conversations':len(conversations),'dev_conversations':len(selected),'dev_documents':sum(len(r['documents']) for r in selected),'dev_questions':sum(len(r['questions']) for r in selected),'dev_question_types':dict(Counter(q['category'] for r in selected for q in r['questions'])),'dev_memory_points':sum(len(r.get('metadata',{}).get('gold_memory_points',[])) for r in selected),'dev_only':True,'test_executed':False}
 for name in ('longmemeval_s','longmemeval_oracle','locomo','perltqa_zh'):
  path=BASE/(name+'.jsonl');sp=BASE/(name+'-split.json')
  manifest=next(r for r in read(BASE/'manifest.json') if r['dataset']==name)
  assert file_hash(path)==manifest['normalized_sha256'] and file_hash(sp)==manifest['split_sha256']
  save(name,readrows(path),read(sp),{str(path):file_hash(path),str(sp):file_hash(sp)},'A: public benchmark; model-judged scores not comparable to official GPT4o scores')
 query=read('docs/evals/chinese-query-current.json');qp=Path(query['files']['queries']['path']).parent
 for r in query['files'].values():assert file_hash(Path(r['path']))==r['sha256']
 save('chinese_queries_v2',readrows(qp/'corpus.jsonl'),read(qp/'split.json'),{str(p):file_hash(p) for p in [qp/'corpus.jsonl',qp/'split.json',qp/'queries.jsonl']},'B/C: frozen source provenance; constructed temporal/update/multi-session FLOW ONLY')
 accepted_path=Path('.local/phase1/round3/new-accounts-v1/blind-adoption-v1/accepted-union-private.jsonl')
 accepted=readrows(accepted_path);freeze=read('docs/evals/reliable-chinese-current.json')
 assert len(accepted)==freeze['accepted_union'] and file_hash(accepted_path)==freeze['items_sha256']
 grouped={}
 for row in accepted:
  cid=row['conversation_id'];r=grouped.setdefault(cid,{'conversation_id':cid,'documents':[{'source_id':s['source_id'],'session_id':s.get('session_id',cid),'role':s['role'],'text':s['text']} for s in row['source']],'questions':[],'metadata':{'gold_memory_points':[],'evidence_level':'turn'}})
  r['metadata']['gold_memory_points'].append({'item_id':row['item_id'],'candidate':row['candidate'],'subject':row['subject']})
 splitpath=BASE/'dulemon-split.json';frozen=read(splitpath);lookup={cid:side for side,ids in frozen.items() for cid in ids}
 projected={'dev':[],'test':[]}
 for cid in grouped:
  canonical='dulemon:DuLeMon/both/train.json:'+str(int(cid.split(':')[1]))
  projected[lookup[canonical]].append(cid)
 assert len(grouped)==533
 save('dulemon_gold',list(grouped.values()),projected,{str(accepted_path):file_hash(accepted_path),str(splitpath):file_hash(splitpath)},'B: AI candidates plus owner confirmation/audit-approved pools; not exhaustive human annotation')
 oldroot=Path('.local/phase1/round3/temporal-v1/ecd-owner');newroot=Path('.local/phase1/round3/ecd180-review-v1/owner-final')
 ecd=[]
 for prefix in (oldroot,newroot):
  for r in readrows(prefix/'negative-private.jsonl'):
   source=json.loads(r['source']);ecd.append({'conversation_id':r['conversation_id'],'documents':source,'questions':[],'metadata':{'gold_memory_points':[],'human_no_memories':True,'annotation_method':'AI 草稿加人工确认','evidence_level':'turn','domain':'customer service, not general dialogue'}})
 ecdsplit=Path('.local/phase1/round3/ecd180-review-v1/sample/split-extended-private.json')
 assert len(ecd)==282
 save('ecd_negative',ecd,read(ecdsplit),{str(ecdsplit):file_hash(ecdsplit),**{str(p):file_hash(p) for p in (oldroot/'negative-private.jsonl',newroot/'negative-private.jsonl')}},'B: AI draft plus owner confirmation, customer service only')
 (ROOT/'manifest.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
 Path('docs/baselines/b0/datasets-v1.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps({k:{s:v[s] for s in ['full_conversations','dev_conversations','dev_documents','dev_questions','dev_memory_points']} for k,v in result.items()}))

if __name__=='__main__':main()
