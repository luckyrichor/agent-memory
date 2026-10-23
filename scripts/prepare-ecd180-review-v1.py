"""Owner-directed random ECD review; no models, no inferred memory labels.

Requires an explicit source-scope decision: fresh unused source contexts require
an append-only split extension, while unreviewed historical contexts inherit exact
old assignments. Never silently equate unreviewed with previously unused.
"""
import argparse
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import random
import zipfile

from agent_memory.evals.chinese_expansion import frozen_extension, unsegment
from agent_memory.evals.datasets import file_hash
from agent_memory.evals.human_review import csv_text, digest

BASE=Path('.local/phase1/chinese-expansion-v2/ecd')
OLD=Path('.local/phase1/round3/reviews/ecd-manual-120.csv')
ARCHIVE=Path('.local/phase1/data/ECD.zip')
HUMAN=('human_memories','human_no_memories','human_reason')


def prepare(mode, output, seed, owner_decision):
    if output.exists() or '.local' not in output.resolve().parts:
        raise ValueError('fresh private output required')
    with OLD.open(encoding='utf-8-sig',newline='') as stream:
        reader=csv.DictReader(stream);columns=list(reader.fieldnames);old=list(reader)
    assert columns==['conversation_id','stratum','split','source','record_sha256',*HUMAN]
    previous={r['conversation_id'] for r in old};assert len(previous)==len(old)==120
    frozen=json.loads((BASE/'split.json').read_text())
    split={cid:side for side,ids in frozen.items() for cid in ids}
    assert len(split)==sum(map(len,frozen.values()))
    assert all(split[r['conversation_id']]==r['split'] for r in old)
    protections={str(OLD):file_hash(OLD),str(BASE/'split.json'):file_hash(BASE/'split.json')}
    for policy in [Path('.local/phase1/round3/followup/protected-hashes.json'),Path('.local/phase1/round3/new-accounts-v1/ecd-unchanged-hashes.json')]:
        for path,h in json.loads(policy.read_text()).items():
            assert file_hash(Path(path))==h
            protections[path]=h
    used=set();inventory={}
    for pattern in ('**/ecd/corpus.jsonl','**/ecd/items.jsonl'):
        for path in sorted(Path('.local/phase1').glob(pattern)):
            for line in path.open():
                r=json.loads(line);cid=r.get('conversation_id')
                if isinstance(cid,str) and cid.startswith('ecd:'):used.add(cid)
            inventory[str(path)]=file_hash(path)
    assert previous<=used and used<=split.keys()
    rng=random.Random(seed);sample=[];population=0;source_rows={}
    source_count=None
    if mode=='unreviewed':
        source_rows={r['conversation_id']:r for r in map(json.loads,(BASE/'corpus.jsonl').open())}
        eligible=sorted(source_rows.keys()-previous)
        chosen=rng.sample(eligible,180);population=len(eligible)
        sample=[source_rows[cid] for cid in chosen]
    else:
        source_manifest=json.loads((BASE/'manifest.json').read_text())
        assert file_hash(ARCHIVE)==source_manifest['archive_sha256']
        seen=set();positive=negative=duplicates=0
        with zipfile.ZipFile(ARCHIVE) as archive:
            assert archive.testzip() is None
            with archive.open(source_manifest['member']) as stream:
                for row_no,raw in enumerate(stream):
                    fields=raw.decode('utf-8').rstrip('\r\n').split('\t')
                    if len(fields)<3 or fields[0] not in {'0','1'}:raise ValueError('malformed original ECD row')
                    if fields[0]=='0':negative+=1;continue
                    positive+=1
                    context=[unsegment(t) for t in fields[1:-1]]
                    key=hashlib.sha256(json.dumps(context,ensure_ascii=False).encode()).hexdigest()
                    if key in seen:duplicates+=1;continue
                    seen.add(key);cid='ecd:train:'+key
                    if cid in used:continue
                    population+=1
                    entry={'conversation_id':cid,'source_row':row_no,'source':[
                        {'source_id':f'turn:{i}','session_id':cid,'role':'source','text':unsegment(t)}
                        for i,t in enumerate(fields[1:])]}
                    if len(sample)<180:sample.append(entry)
                    else:
                        slot=rng.randrange(population)
                        if slot<180:sample[slot]=entry
        source_count={'positive_response_rows':positive,'unrelated_negative_response_rows_excluded':negative,
                      'unique_contexts':len(seen),'duplicate_context_rows':duplicates,
                      'prior_used_excluded':len(used),'source_archive_sha256':file_hash(ARCHIVE)}
        extended=frozen_extension(frozen,[r['conversation_id'] for r in sample],seed=42)
        assert all(extended[side][:len(ids)]==ids for side,ids in frozen.items())
        split={cid:side for side,ids in extended.items() for cid in ids}
    assert len(sample)==180 and len({r['conversation_id'] for r in sample})==180
    assert not ({r['conversation_id'] for r in sample}&previous)
    if mode=='fresh':assert not ({r['conversation_id'] for r in sample}&used)
    manual=[]
    for source in sample:
        cid=source['conversation_id']
        row={'conversation_id':cid,'stratum':'simple_random_unstratified','split':split[cid],
             'source':source['source'],**{k:None for k in HUMAN}}
        row['record_sha256']=digest(row);manual.append(row)
    rng.shuffle(manual)
    output.mkdir(parents=True,mode=0o700)
    private=output/'ecd180-preparation.csv'
    with private.open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=columns);writer.writeheader()
        for row in manual:writer.writerow({k:'' if k in HUMAN else csv_text(row[k]) for k in columns})
    (output/'ecd180-preparation.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in manual))
    if mode=='fresh':(output/'split-extended-private.json').write_text(json.dumps(extended,indent=2)+'\n')
    with private.open(encoding='utf-8-sig',newline='') as stream:exported=list(csv.DictReader(stream))
    for row,csvrow in zip(manual,exported,strict=True):
        assert all(csvrow[k]=='' for k in HUMAN)
        assert all(csvrow[k]==csv_text(row[k]) for k in columns if k not in HUMAN)
    assert all(file_hash(Path(p))==h for p,h in protections.items())
    report={'mode':mode,'owner_decision':owner_decision,'seed':seed,'conversations':len(manual),
            'sampling_population':population,'sampling':'simple random without replacement; no model scores or label files read; full source conversations, no truncation',
            'old_human_review_overlap':0,'all_previous_model_source_overlap':len({r['conversation_id'] for r in manual}&used),
            'prior_used_conversations':len(used),'previously_human_reviewed':len(previous),
            'split_counts':dict(Counter(r['split'] for r in manual)),
            'stratum_counts':dict(Counter(r['stratum'] for r in manual)),
            'human_columns_all_blank':True,'columns':columns,'row_order_shuffled':True,
            'source_counts':source_count,'source_inventory_sha256':inventory,'protected_files_sha256':protections,
            'old_frozen_split_unchanged':True,'split_extension_seed':42 if mode=='fresh' else None,
            'private_csv_sha256':file_hash(private),'private_csv_bytes':private.stat().st_size,
            'private_jsonl_sha256':file_hash(output/'ecd180-preparation.jsonl'),
            'raw_private_only':True,'raw_text_not_published':True,'model_calls':0,
            'provisional_only':True,'owner_confirmed_new_negative':0,'adoption_changed':False,
            'no_model_memory_judgment_filter':True,
            'response_label_note':'ECD 1 identifies the matched response; 0 is an unrelated candidate response, not a memory-negative label',
            'source_domain':'customer service; not representative of general dialogue'}
    (output/'manifest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    for p in output.iterdir():p.chmod(0o600)
    print(json.dumps({k:report[k] for k in ['mode','seed','conversations','sampling_population','split_counts','old_human_review_overlap','all_previous_model_source_overlap','private_csv_sha256']},ensure_ascii=False))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--mode',choices=['fresh','unreviewed'],required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--seed',type=int,default=20261101)
    p.add_argument('--owner-decision',required=True);args=p.parse_args()
    prepare(args.mode,args.output,args.seed,args.owner_decision)
