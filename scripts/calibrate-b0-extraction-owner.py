"""Join immutable owner extraction judgments; publish aggregates only."""
from collections import defaultdict
import csv
import hashlib
import json
from pathlib import Path

from agent_memory.evals.metrics import ratio

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'.local/phase2/b0/completion-20261028'
PUBLIC=ROOT/'docs/reports/phase2-b0-completion-2026-10-28'


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def agreement(pairs):
    matrix=[[0,0],[0,0]]  # rows human0/1, columns judge0/1
    for human,judge in pairs:matrix[human][judge]+=1
    n=len(pairs);accuracy=(matrix[0][0]+matrix[1][1])/n
    expected=sum(sum(matrix[i])*sum(matrix[j][i] for j in range(2)) for i in range(2))/(n*n)
    kappa=(accuracy-expected)/(1-expected) if expected!=1 else None
    positives=matrix[0][1]+matrix[1][1]
    return {'n':n,'accuracy':accuracy,'cohen_kappa':kappa,'confusion_human_rows_judge_columns':matrix,
            'judge_true_human_false':matrix[0][1],'false_positive_fraction_all':matrix[0][1]/n,
            'false_positive_fraction_judge_positive':matrix[0][1]/positives if positives else None,
            'eligible':accuracy>=.9 or (kappa is not None and kappa>=.7)}


def main():
    private=BASE/'extraction-owner-20261031';filled=private/'extraction-owner-review-private_filled.csv'
    original=BASE/'extraction-v2/extraction-owner-review-private.csv'
    rows=list(csv.DictReader(filled.open(encoding='utf-8-sig')))
    source=list(csv.DictReader(original.open(encoding='utf-8-sig')))
    human={r['item_id']:r for r in rows}
    assert len(rows)==len(human)==len(source)==73
    assert set(human)=={r['item_id'] for r in source}
    assert all(r[k]==human[r['item_id']][k] for r in source for k in ['question','reference','answer'])
    assert all(r['human_correct'].strip() in ('0','1') and r['human_reason'].strip() for r in rows)
    cases=json.loads((BASE/'extraction-v2/cases-private.json').read_text())
    answers=json.loads((BASE/'extraction-v2/assessments-private.json').read_text())
    index={};totals=defaultdict(lambda:[0,0,0,0])
    for case in cases:
        for task,items in [('precision',case['candidates']),('recall',case['gold'])]:
            for item in items:
                rawid=item['id'] if task=='precision' else item['item_id']
                ident=('ex-p-' if task=='precision' else 'ex-r-')+digest([case['id'],rawid])[:20]
                assert ident in human and ident not in index
                index[ident]=(case['id'],rawid,task,case['conversation_id'])
                v=totals[case['conversation_id']];offset=0 if task=='precision' else 2
                v[offset]+=int(human[ident]['human_correct']);v[offset+1]+=1
    assert len(index)==73
    precision=ratio([(v[0],v[1]) for v in totals.values()]).to_dict()
    recall=ratio([(v[2],v[3]) for v in totals.values()]).to_dict()
    p,r=precision['value'],recall['value'];models={};joined=[]
    for model in ['glm-5.2','minimax-m3']:
        lookup={a['case_id']:a['value'] for a in answers if a['model']==model}
        pairs=defaultdict(list)
        for ident,(caseid,rawid,task,conversation) in index.items():
            value=lookup[caseid];assert value is not None
            prediction=int(next(c['correct'] for c in value['candidates'] if c['id']==rawid)) if task=='precision' else int(rawid in value['covered_gold_ids'])
            label=int(human[ident]['human_correct']);pairs['overall'].append((label,prediction));pairs[task].append((label,prediction))
            joined.append({'item_id':ident,'model':model,'task':task,'human':label,'judge':prediction,'conversation_id':conversation})
        models[model]={task:agreement(values) for task,values in pairs.items()}
    joined_path=private/'joined-private.json';joined_path.write_text(json.dumps(joined)+'\n');joined_path.chmod(0o600)
    report={'rows':73,'original_content_unchanged':True,'all_reasons_present':True,
            'filled_sha256':hashlib.sha256(filled.read_bytes()).hexdigest(),'original_sha256':hashlib.sha256(original.read_bytes()).hexdigest(),
            'models':models,'human_metrics':{'EX1':precision,'EX2':recall,'EX3':2*p*r/(p+r) if p+r else 0},
            'method':'Full73 sampled extraction judgments, no extra model calls;43 candidate validity and30 gold coverage labels. Human EX1/EX2 use conversation-cluster intervals from8 conversations across3 repeats.',
            'threshold':'Per-task kappa>=0.7 OR accuracy>=0.9. Failing task judge cannot supply formal metric; full owner judgments directly supply sampled human EX1/EX2.',
            'limitations':['DuLeMon selected dev8 conversations only; not all dev data or a test-set estimate.',
                           'EX5 wrong-subject sublabel is not separately calibrated by these binary validity/coverage judgments and remains diagnostic.',
                           'Extraction judge repeat stability is not covered by QA100x3 results.',
                           'DeepSeek is also a gold annotation vendor; same-vendor extraction can bias scores upward; joint two-vendor gold retention partly mitigates this.'],
            'phase2_accepted':False,'full_aggregate_ready':False}
    (PUBLIC/'extraction-owner-calibration.json').write_text(json.dumps(report,indent=2)+'\n')
    lines=['# 抽取专项负责人校准（聚合）','',
           '73条全部对齐，原题、参考与答案未改，人工判定与理由完整；原始标签和理由仅在服务器私有目录。','',
           '| 裁判 | 分层 | n | 一致率 | Cohen κ | 判对但人工判错 | 采用门槛 |',
           '| --- | --- | --- | --- | --- | --- | --- |']
    for model,parts in models.items():
        for task,m in parts.items():
            k='不可定义' if m['cohen_kappa'] is None else f"{m['cohen_kappa']:.4f}"
            lines.append(f"| {model} | {task} | {m['n']} | {m['accuracy']:.2%} | {k} | {m['judge_true_human_false']}/{m['n']} | {'达标' if m['eligible'] else '不达标'} |")
    lines.extend(['',f"人工精确率EX1：{precision['numerator']}/{precision['denominator']}={p:.2%}；95%会话簇区间{precision['ci95']}。",
                  f"人工召回率EX2：{recall['numerator']}/{recall['denominator']}={r:.2%}；95%会话簇区间{recall['ci95']}。",f"F1：{report['human_metrics']['EX3']:.4f}。",'',report['threshold'],'']+['- '+s for s in report['limitations']])
    (PUBLIC/'extraction-owner-calibration.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps({'validated_rows':73,'models':models,'human_metrics':report['human_metrics']}))


if __name__=='__main__':main()
