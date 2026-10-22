"""Read-only source inventory. No candidate export, sampling, model calls or incremental import."""
import json
import re
import zipfile
from collections import Counter
from pathlib import Path

from agent_memory.evals.evidence_v3 import read_rows, sha
from agent_memory.evals.pool_planning import source_record

ROOT=Path('.local/phase1/round3/pool-refresh-v3-v3')
archive=Path('.local/phase1/data/DuLeMon.zip')
with zipfile.ZipFile(archive) as z:
 raw={name:[json.loads(s) for s in z.read(name).decode().splitlines() if s.strip()]
      for name in z.namelist() if name.endswith('.json')}
member='DuLeMon/both/train.json';rows=raw[member]
used=set();origins={};hashes={str(archive):sha(archive)}
for p in sorted(Path('.local/phase1').glob('chinese-expansion-v*/dulemon/manifest.json')):
 d=json.loads(p.read_text());indices=set(d['previously_used_indices'])|set(d['new_indices'])
 used|=indices;origins[str(p)]={'used_indices':len(indices)};hashes[str(p)]=sha(p)
query_used=set()
for p in sorted(Path('.local/phase1/round3').glob('**/contexts.jsonl')):
 if 'chinese-quer' not in str(p):continue
 indices=set()
 for r in read_rows(p):
  m=re.fullmatch(r'dulemon:DuLeMon/both/train.json:(\d+)',r.get('conversation_id',''))
  if m:indices.add(int(m[1]))
 if indices:
  query_used|=indices;origins[str(p)]={'query_source_indices':len(indices)};hashes[str(p)]=sha(p)
annotations_used=used.copy();used|=query_used
records=[source_record(r) for r in rows]
used_hashes={records[i][0] for i in used if records[i][0]}
seen=set();eligible=[];excluded=Counter();candidate_total=0
for i,(h,n,error) in enumerate(records):
 if error:excluded[error]+=1;continue
 if i in used:excluded['used-source-index']+=1;continue
 if h in used_hashes:excluded['duplicate-of-used-dialogue']+=1;continue
 if h in seen:excluded['duplicate-of-unused-dialogue']+=1;continue
 seen.add(h);eligible.append(i);candidate_total+=n
source_split_path=Path('.local/phase1/normalized-v3/dulemon-split.json')
split=json.loads(source_split_path.read_text());hashes[str(source_split_path)]=sha(source_split_path)
lookup={cid:side for side,ids in split.items() for cid in ids}
counts=Counter(lookup.get(f'dulemon:DuLeMon/both/train.json:{i}','missing') for i in eligible)
# Local index/hash list only; no source text/candidates exported.
(ROOT/'reserve-indices-private.json').write_text(json.dumps(eligible)+'\n')
report={
 'scope':member,'raw_sizes':{k:len(v) for k,v in raw.items()},'raw_train_dialogues':len(rows),
 'annotation_used_unique':len(annotations_used),'query_used_unique':len(query_used),
 'annotation_query_overlap':len(annotations_used&query_used),'used_union':len(used),
 'remaining_before_field_and_dedup':len(rows)-len(used),'available_field_valid_unique':len(eligible),
 'available_native_candidate_slots':candidate_total,
 'candidates_per_available_dialogue':candidate_total/len(eligible) if eligible else None,
 'excluded_counts':dict(excluded),'inherited_split_counts':dict(counts),
 'self_schema_excluded':sum(len(v) for k,v in raw.items() if '/self/' in k),
 'native_dev_test_held_out':sum(len(v) for k,v in raw.items() if '/both/' in k and k!=member),
 'definition':'Never selected for known annotation/review export nor frozen Chinese queries; normalized full archive parsing is not counted as task use. Exact normalized role/text hashes deduplicate, not semantic near-duplicates. Full negative dialogues require separate owner confirmation.',
 'origin_manifests':origins,'input_hashes':hashes,'incremental_sampling_started':False,
}
(ROOT/'reserve-summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:report[k] for k in ('raw_train_dialogues','annotation_used_unique','query_used_unique','used_union','available_field_valid_unique','available_native_candidate_slots','inherited_split_counts')}))
