"""Audit aggregate capacity, private exception logs and repeat-level uncertainty."""
from collections import Counter
import hashlib
from itertools import product
import json
from pathlib import Path
import re
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
CAP = ROOT/'.local/phase2/b0/completion-20261028/capacity'
PUBLIC = ROOT/'docs/reports/phase2-b0-completion-2026-10-28'
sys.path.insert(0,str(ROOT/'scripts'))
from b0_accounts import credential


def percentile(values, probability):
    values = sorted(values); index = (len(values)-1)*probability
    lo = int(index); hi = min(lo+1,len(values)-1)
    return values[lo]+(values[hi]-values[lo])*(index-lo)


def main():
    original = PUBLIC/'tx2-public-load.json'
    data = json.loads(original.read_text()); groups = []
    secrets = [credential(a)[2].encode() for a in ['deepseek-direct','tokenhub-primary','tokenhub-secondary']]
    vector_db = sqlite3.connect('file:'+str(CAP/'vectors-private.sqlite')+'?mode=ro',uri=True)
    log_audits = []
    for size,label in [(10000,'tx2-10k'),(100000,'tx2-100k')]:
        points = [p for p in data['points'] if p['size']==size]
        assert len(points)==3 and all(p['load_host_resources_valid'] for p in points)
        metrics = [p['measured_metrics'] for p in points]
        requests = [m['b0_sample_requests']['count'] for m in metrics]
        errors = [m['b0_sample_errors']['count'] for m in metrics]
        p95 = [m['b0_sample_client_ms']['p(95)'] for m in metrics]
        boot_errors = []; boot_p95 = []
        for indices in product(range(3),repeat=3):
            boot_errors.append(sum(errors[i] for i in indices)/sum(requests[i] for i in indices))
            boot_p95.append(sum(p95[i] for i in indices)/3)
        statuses = Counter(); errors_found = Counter(); sql_total = Counter(); sql_n = Counter()
        for repeat in [1,2,3]:
            name = f'{label}-r{repeat}';path = CAP/(name+'-app-private.log');raw = path.read_bytes()
            for needle in ['QueuePool limit','QueryCanceled','DiskFull','OutOfMemory']:
                errors_found[needle] += raw.count(needle.encode())
            ids = {int(x) for x in re.findall('虚构压测记录([0-9]{6})'.encode(),raw)}
            complete_hits = 0
            for index in ids:
                row = vector_db.execute('SELECT text FROM vectors WHERE id=?',(index,)).fetchone()
                if row: complete_hits += raw.count(row[0].encode())
            log_audits.append({'artifact':path.name,'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),
                               'complete_fictional_body_occurrences':complete_hits,
                               'credential_occurrences':sum(raw.count(s) for s in secrets)})
            for line in (CAP/(name+'-http-private.jsonl')).read_text().splitlines():
                row=json.loads(line);statuses[str(row.get('status'))]+=1
                for category,elapsed in row.get('sql_ms',{}).items():
                    sql_total[category]+=elapsed;sql_n[category]+=1
        group = {'size':size,'repeats':3,'measured_requests':sum(requests),'measured_errors':sum(errors),
                 'error_fraction':sum(errors)/sum(requests),
                 'per_repeat_error_fractions':[e/n for e,n in zip(errors,requests)],
                 'error_fraction_ci95_repeat_bootstrap':[percentile(boot_errors,.025),percentile(boot_errors,.975)],
                 'mean_per_repeat_client_p95_ms':sum(p95)/3,
                 'mean_per_repeat_p95_ci95_repeat_bootstrap_ms':[percentile(boot_p95,.025),percentile(boot_p95,.975)],
                 'dropped_arrivals_including_warmup':sum(m['dropped_iterations']['count'] for m in metrics),
                 'all_load_host_resources_valid':True,'capacity_acceptance_pass':False,
                 'observed_server_statuses_including_warmup_and_shutdown':dict(statuses),
                 'observed_error_string_counts_including_shutdown':dict(errors_found),
                 'mean_recorded_sql_category_ms_including_warmup_and_shutdown':{k:sql_total[k]/sql_n[k] for k in sql_total}}
        groups.append(group)
    vector_db.close()
    report = {'source_report_sha256':hashlib.sha256(original.read_bytes()).hexdigest(),'groups':groups,
              'log_audits':log_audits,'complete_body_log_occurrences':sum(r['complete_fictional_body_occurrences'] for r in log_audits),
              'credential_log_occurrences':sum(r['credential_occurrences'] for r in log_audits),
              'performance_pass':False,'SC4_pass':False,'phase2_accepted':False,
              'uncertainty_method':'Exact27 resamples of3 independent API-process repeats with replacement; percentile95% interval. n=3 has low precision. Latency CI is the mean of per-repeat p95s, not a pooled per-request p95 CI.',
              'interpretation':['Use error count/request count, not the k6 Counter rate field, for error fractions.',
                 'All six load-host resource checks pass, but every run dropped arrivals; no sustainable1QPS capacity claim.',
                 'Slow lexical SQL and pool exhaustion are observed; this is not proof of a single root cause or an optimization result.',
                 'Server status and SQL logs include warmup and shutdown; client timeout and later server response counts cannot be directly equated.',
                 'Canceled query exceptions during cleanup can serialize SQL parameters containing full fictional queries. This fails the body-log requirement even though no real user conversation was used.',
                 'Both machines are in ap-shanghai. Independent-host public ingress was tested; cross-region path was not.']}
    (PUBLIC/'tx2-results-audit.json').write_text(json.dumps(report,indent=2)+'\n')
    lines=['# B0独立公网压测核验（失败结果）','',
           '固定B0@1e9d6f3，腾讯原生1024维，完全虚构32字符性能语料；TX2独立发压、TX隔离服务。每规模3轮、1QPS，每轮60秒预热+300秒测量。','',
           '| 记忆数 | 测量请求 | 失败 | 失败率 | 95%重复级区间 | 每轮客户端p95约 | 丢弃到达（含预热） |','| --- | --- | --- | --- | --- | --- | --- |']
    for g in groups:
        lo,hi=g['error_fraction_ci95_repeat_bootstrap']
        lines.append(f"| {g['size']} | {g['measured_requests']} | {g['measured_errors']} | {g['error_fraction']:.2%} | {lo:.2%}–{hi:.2%} | {g['mean_per_repeat_client_p95_ms']/1000:.2f}秒 | {g['dropped_arrivals_including_warmup']} |")
    lines.extend(['','两端资源采样完整，发压端资源均合格；所有运行均有丢弃到达，不能通过1QPS可持续容量验收。',
                  '',f"异常日志完整虚构查询正文命中{report['complete_body_log_occurrences']}次，所检查的API密钥命中{report['credential_log_occurrences']}次。正文出现在取消查询异常的SQL参数中，SC4未通过。报告只给聚合数字，原始异常和文本留在服务器私有目录。",'',report['uncertainty_method'],'']+
                 ['- '+s for s in report['interpretation']])
    (PUBLIC/'tx2-results-audit.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps({'groups':[{'size':g['size'],'errors':g['measured_errors'],'requests':g['measured_requests']} for g in groups],
                      'body_log_occurrences':report['complete_body_log_occurrences'],'credential_occurrences':report['credential_log_occurrences']}))


if __name__ == '__main__':
    main()
