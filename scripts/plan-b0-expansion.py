"""Count a dev-only, category-balanced expansion before any vendor request."""
import collections, hashlib, json, math, random
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'.local/phase2/b0/expansion-20261101'
registry=json.loads((ROOT/'docs/baselines/b0/datasets-v1.json').read_text())
targets={'perltqa_zh':300,'chinese_queries_v2':150,'longmemeval_oracle':50,'longmemeval_s':50}
plan={}; selection={}
for name,target in targets.items():
    source=ROOT/registry[name]['path']
    assert hashlib.sha256(source.read_bytes()).hexdigest()==registry[name]['sha256']
    with source.open() as f: corpus=[json.loads(line) for line in f if line.strip()]
    bytype=collections.defaultdict(list)
    for conv in corpus:
        excluded=set(conv.get('metadata',{}).get('flow_only_categories',[])) if name=='chinese_queries_v2' else set()
        for q in conv['questions']:
            if q['category'] not in excluded: bytype[q['category']].append((conv['conversation_id'],q['question_id']))
    rng=random.Random(42)
    for values in bytype.values():rng.shuffle(values)
    picked=[]
    while len(picked)<target:
        before=len(picked)
        for category in sorted(bytype):
            if bytype[category] and len(picked)<target:picked.append(bytype[category].pop())
        assert len(picked)>before
    ids=collections.defaultdict(list)
    for cid,qid in picked:ids[cid].append(qid)
    chosen=[c for c in corpus if c['conversation_id'] in ids]
    chunks=sum(math.ceil(len(d['text'])/4000) for c in chosen for d in c['documents'])
    chars=sum(len(d['text']) for c in chosen for d in c['documents'])
    vectors=chunks*24+target*18
    plan[name]={'questions':target,'conversations':len(chosen),'source_chunks':chunks,'source_characters':chars,'answer_calls':target*24,'primary_judge_calls':target*24,'source_extraction_calls':chunks*3,'conservative_vector_calls':vectors,'vector_calls_with_25pct_reserve':math.ceil(vectors*1.25),'source_sha256':registry[name]['sha256']}
    selection[name]={'source_sha256':registry[name]['sha256'],'questions_by_conversation':dict(ids)}
plan['totals']={k:sum(v[k] for v in plan.values()) for k in ['questions','conversations','source_chunks','source_characters','answer_calls','primary_judge_calls','source_extraction_calls','conservative_vector_calls','vector_calls_with_25pct_reserve']}
plan['totals']['vector_minimum_pacing_hours_conservative']=plan['totals']['conservative_vector_calls']*1.2/3600
plan['notes']=['No vendor call performed by this planner. Request counts exclude retries and cross-reference up to 300.','Vector count is a conservative planning bound, not a bill or balance check; extracted memories are response dependent.','No prior cached vectors enabled, matching original config.','LoCoMo frozen dev has only 3 conversations; owner decision pending; not included in totals.','Test registry/files untouched. Quality targets use category-balanced round robin seed42.']
OUT.mkdir(parents=True,exist_ok=True,mode=0o700)
for name,data in [('selection-private.json',selection),('call-estimate.json',plan)]:
    path=OUT/name;path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n');path.chmod(0o600)
public=ROOT/'docs/reports/phase2-b0-expansion-2026-11-01/call-estimate.json';public.write_text(json.dumps(plan,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(plan,ensure_ascii=False,indent=2))
