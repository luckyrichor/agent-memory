"""Create a reviewable aggregate-only B0 report bundle, retaining failed/unmeasured scope."""
from collections import Counter
from collections import defaultdict
import csv
from datetime import datetime
import hashlib
import json
from itertools import product
from pathlib import Path
import random
import subprocess
import sys
import zipfile
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'.local/phase2/b0/frozen-deepseek-20261026-v1/recovery-run-2'
SUP=ROOT/'docs/reports/phase2-b0-completion-2026-10-28'


def read(path):return json.loads(path.read_text())
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def fmt(value):return '未测/不适用' if value is None else f'{value:.4f}' if isinstance(value,(float,int)) else str(value)
def estimate(value):
    if not value:return '未测/不适用'
    return fmt(value.get('value'))+' ['+', '.join(fmt(x) for x in (value.get('ci95') or []))+']'

def percentile(values,p):
    values=sorted(values);index=(len(values)-1)*p;lo=int(index);hi=min(lo+1,len(values)-1)
    return values[lo]+(values[hi]-values[lo])*(index-lo)


def main():
    now=datetime.now(ZoneInfo('Asia/Shanghai'));head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    source=ROOT/'.local/phase2/b0/source-B0'
    baseline=subprocess.check_output(['git','rev-parse','HEAD'],cwd=source,text=True).strip()
    assert baseline=='1e9d6f3b25b58c85792344000d7e1b5a71a79737'
    assert not subprocess.check_output(['git','status','--porcelain'],cwd=source,text=True).strip()
    original=read(BASE/'aggregate/report.json');assert len(original['measurements'])==40
    assert sum(m['rows'] for m in original['measurements'].values())==1272
    assert sum(m['rows'] for m in original['flow_only'].values())==288
    for m in original['measurements'].values():
        assert m['answer_models']==['deepseek-v4-pro'] and m['judge_models']==['glm-5.2']
    qa=read(ROOT/'docs/reports/phase2-b0-owner-calibration-2026-10-27/calibration-report.json')
    ex=read(SUP/'extraction-owner-calibration.json')
    read_pf=read(SUP/'tx2-public-load.json');extra_pf=read(SUP/'tx2-extra-public-load.json')
    assert read_pf['status']==extra_pf['status']=='measurements_complete'
    assert len(read_pf['points'])==6 and len(extra_pf['points'])==12
    assert all(p['load_host_resources_valid'] for p in read_pf['points']+extra_pf['points'])
    assert all(m['overall']['adoptable_on_this_calibration'] for m in qa['judge_models'].values())
    assert all(v['eligible'] for m in ex['models'].values() for v in m.values())
    output=ROOT/'docs/reports'/('b0-aggregate-'+now.strftime('%Y%m%d-%H%M%S'));output.mkdir()
    def write_json(name,data):(output/name).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
    def write_csv(name,rows):
        assert rows
        with (output/name).open('w',encoding='utf-8-sig',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    measures=[];types=[];worst=[]
    for table,m in original['measurements'].items():
        dataset,mode,system=table.split('/')
        scope='B类质量题；C类流程题另列' if dataset=='chinese_queries_v2' else '开发集抽样质量'
        for metric,value in m['values'].items():
            measures.append(dict(dataset=dataset,mode=mode,system=system,scope=scope,metric=metric,value=value.get('value'),numerator=value.get('numerator'),denominator=value.get('denominator'),conversation_clusters=value.get('n'),ci95_low=(value.get('ci95') or [None,None])[0],ci95_high=(value.get('ci95') or [None,None])[1]))
        for kind,values in original['by_type'].get(table,{}).items():
            for metric,value in values.items():
                types.append(dict(dataset=dataset,mode=mode,system=system,question_type=kind,scope=scope,metric=metric,value=value.get('value'),denominator=value.get('denominator'),conversation_clusters=value.get('n'),ci95_low=(value.get('ci95') or [None,None])[0],ci95_high=(value.get('ci95') or [None,None])[1]))
        for kind in original['worst_types'].get(table,[]):
            v=original['by_type'][table][kind].get('E1',{})
            worst.append(dict(dataset=dataset,mode=mode,system=system,worst_question_type=kind,E1=v.get('value'),denominator=v.get('denominator'),conversation_clusters=v.get('n')))
    write_csv('metrics.csv',measures);write_csv('by-type.csv',types);write_csv('worst-types.csv',worst)
    write_json('flow-only.json',original['flow_only'])
    cases=[{k:v for k,v in c.items() if k!='private_source'} for c in original['failure_cases']]
    write_json('failure-cases.json',{'count_all':original['failure_count'],'reason_counts':original['failure_reason_counts'],'examples':cases,'privacy':'Only failure IDs, task strata and reason codes; no conversations, answers or human labels.'})
    write_json('qa-calibration.json',qa);write_json('extraction-calibration.json',ex)
    human_rows=read(ROOT/'.local/phase2/b0/completion-20261028/extraction-owner-20261031/joined-private.json')
    grouped=defaultdict(lambda:[0,0,0,0])
    for row in human_rows:
        if row['model']!='glm-5.2':continue
        value=grouped[row['conversation_id']];index=0 if row['task']=='precision' else 2
        value[index]+=row['human'];value[index+1]+=1
    assert len(grouped)==8 and sum(x[1]+x[3] for x in grouped.values())==73
    rng=random.Random(42);f1_samples=[];units=list(grouped.values())
    for _ in range(1000):
        sampled=[rng.choice(units) for _ in units];counts=[sum(x[i] for x in sampled) for i in range(4)]
        if not counts[1] or not counts[3]:continue
        precision,recall=counts[0]/counts[1],counts[2]/counts[3]
        f1_samples.append(2*precision*recall/(precision+recall) if precision+recall else 0)
    f1_ci=[percentile(f1_samples,.025),percentile(f1_samples,.975)]
    write_json('extraction-F1-interval.json',{'value':ex['human_metrics']['EX3'],'ci95':f1_ci,'clusters':8,'bootstrap_draws':1000,'valid_draws':len(f1_samples),'seed':42,'method':'Joint resampling of conversation precision/recall counts; ratio of sums then F1. Same repeated conversation kept as one unit.'})
    for name in ['tokenizer','recovery100k','provider-faults','provider-exhaustion','worker-crash','remaining-faults','search-degradation-verified','disk-full','extraction-boundaries','log-leak-check','all-pressure-log-audit','tx2-results-audit','tx2-extra-results-audit']:
        write_json(name+'.json',read(SUP/(name+'.json')))
    for key in ['preference_question_metrics','session_oracle_reference','ecd_false_extraction','extraction_failure_rates_EX8','provider_egress','queue_controls','fullchain_diagnosis','candidate_confirmation_audit']:
        write_json(key+'.json',original[key])
    write_json('datasets.json',{name:{k:v for k,v in d.items() if k in ['sha256','data_level','full_conversations','dev_conversations','dev_documents','dev_questions','dev_memory_points','dev_only','test_executed']} for name,d in original['data'].items()})
    measured={'EX1':'人工73条中的43条；只限8会话样本','EX2':'人工73条中的30条；只限8会话样本','EX3':'同一人工样本F1，联合会话簇区间见extraction-F1-interval.json','EX8':'当前运行失败/回退尝试，按数据集记录','LC5':'有限状态矩阵穷举，不外推全部请求','RT1':'分表Recall@k，分母/区间在metrics.csv','RT2':'分表Precision@k','RT3':'分表MRR','RT5':'分题型点估计、区间与最差层','RT6':'拒答题子表','CX1':'390真实上下文的tokenizer对照','CX2':'固定tokenizer与8次API usage差分核验','E1':'QA300校准后的固定主裁判标签；仅冻结抽样','E2':'配对系统差及区间','E5':'偏好题子表','E6':'会话级oracle参照，非理论绝对上限','PF1':'两规模1QPS×3次，严重失败','PF2':'两规模1QPS×3次；0观察错误不等于总体零风险','PF3':'两规模1QPS×3次，严重失败','PF9':'每轮两端CPU/内存及服务端磁盘IO、连接采样','RL1':'冻结控制样本100并发幂等','RL2':'冻结控制样本20并发CAS','RL3':'真实租约过期和旧worker拒绝','RL6':'100k跨机恢复及RLS/角色验证','SC1':'已知外租户ID攻击控制样本','SC3':'无权限JWT读写检索控制样本','SC4':'失败：18轮日志117次完整虚构正文命中'}
    partial={'EX4':'客服负样本8会话，不能外推所有对话','EX6':'敏感输出/输入边界夹具，不是一般化漏放率','EX9':'HTTP尝试级延迟/usage，不等于单事件端到端','LC4':'到期过滤控制样本','LC7':'逻辑删除残留已观察；完整物理/备份清除未测','RT10':'过滤控制样本','RT11':'分页单测不等于规模化分页观测','CX6':'边界指令/权限观察，非完整上下文注入成功率','PF4':'固定1QPS到达和完成情况，非最大吞吐','PF5':'1万/10万两个规模点，非完整曲线','PF7':'DB入队到完成；未测公网客户端可见新鲜度','PF8':'队列状态/重试/完成观测，非完整积压波次试验','RL4':'指定失败夹具的重试/死信；非全业务最终完成率','RL5':'重启后十个成功写入；非p95恢复到健康基线','RL7':'本次压测错误比例；非长期SLA','SC2':'候选指令文字与scope/authority边界，非完整污染评测','SC5':'角色级真实usage，不作不一致分母的千写入归一化','SC6':'角色级真实usage，未独立归一化千检索','SC8':'发送供应商正文UTF8字节；不是已证实的地理跨境量'}
    gaps={'EX5':'未独立人工标注归属子标签','EX7':'未形成独立误拦金标准','LC1':'未形成适用确认金标准','LC2':'未形成适用确认金标准','LC3':'未形成适用确认金标准','LC6':'未做长期增长跟踪','RT4':'缺独立分级相关性观测','RT7':'降级不是受控通道消融','RT8':'未做融合参数扫描','RT9':'方舟禁用；未做公平向量型号对照','CX3':'未独立测渲染后关键信息保留','CX4':'局部截断观察不等于损失率','CX5':'缺冗余金标准','E3':'未独立形成逐有效正确答案token归一化','E4':'问答错误不等于幻觉；缺专门幻觉标注','PF6':'未做精确/近似索引对照','PF10':'80%热租户是工作负载，不是已测公平性','SC7':'预计算caller向量不能证明运行时缓存收益','OP1':'没有指定迁移/版本回滚目标','OP2':'固定型号队列重建不等于流量下全量重建可用性'}
    registry=[]
    for entry in original['metric_coverage']:
        key=entry['id'];status='已测（限定范围）' if key in measured else '局部观察' if key in partial else '未测'
        registry.append(dict(id=key,name=entry['name'],measurement_status=status,scope=(measured|partial|gaps).get(key,'未取得可采纳观测，不能作通过结论')))
    assert len(registry)==66
    write_csv('metric-coverage.csv',registry)
    pairs=[]
    for group in ['paired_comparisons','full_minus_direct']:
        for key,v in original[group].items():pairs.append(dict(comparison_family=group,comparison=key,delta=v.get('delta'),ci95_low=(v.get('ci95') or [None,None])[0],ci95_high=(v.get('ci95') or [None,None])[1],method=v.get('method',''),conversation_clusters=v.get('conversation_clusters'),paired_rows=v.get('paired_rows')))
    write_csv('paired-comparisons.csv',pairs)
    perf=[]
    for p in read_pf['points']+extra_pf['points']:
        m=p['measured_metrics'];n=m['b0_sample_requests']['count'];e=m['b0_sample_errors']['count'];trend=m.get('b0_sample_client_ms') or {}
        perf.append(dict(workload=p.get('workload','search'),size=p['size'],repeat=p['repeat'],rate_per_second=1,measured_requests=n,errors=e,error_fraction=e/n,client_p50_ms=trend.get('med'),client_p95_ms=trend.get('p(95)'),dropped_arrivals_including_warmup=(m.get('dropped_iterations') or {}).get('count',0),load_resources_valid=p['load_host_resources_valid'],confirmed_writes_including_warmup=p.get('client_confirmed_writes'),confirmed_missing=p.get('confirmed_missing'),completed_embedding_jobs=p.get('completed_embedding_jobs'),completed_queue_p95_ms=p.get('completed_queue_p95_ms')))
    write_csv('performance-trials.csv',perf)
    perf_groups=[]
    for kind in ['search','write','context']:
        for size in [10000,100000]:
            a=[r for r in perf if r['workload']==kind and r['size']==size];assert len(a)==3
            errors=[];p95=[]
            for indices in product(range(3),repeat=3):
                errors.append(sum(a[i]['errors'] for i in indices)/sum(a[i]['measured_requests'] for i in indices))
                p95.append(sum(a[i]['client_p95_ms'] for i in indices)/3)
            perf_groups.append(dict(workload=kind,size=size,error_fraction=sum(r['errors'] for r in a)/sum(r['measured_requests'] for r in a),error_ci95_low=percentile(errors,.025),error_ci95_high=percentile(errors,.975),mean_per_trial_p95_ms=sum(r['client_p95_ms'] for r in a)/3,mean_p95_ci95_low_ms=percentile(p95,.025),mean_p95_ci95_high_ms=percentile(p95,.975),bootstrap_unit='three repeats; exact27 resamples; low precision; not pooled per-request CI'))
    write_csv('performance-group-intervals.csv',perf_groups)
    resource_rows=[]
    cap=ROOT/'.local/phase2/b0/completion-20261028/capacity'
    for point in read_pf['points']+extra_pf['points']:
        kind=point.get('workload','search');size=point['size'];repeat=point['repeat']
        label=f'tx2-{size//1000}k' if kind=='search' else f'tx2-{kind}-{size//1000}k'
        path=cap/f'{label}-r{repeat}-server-private.jsonl'
        samples=[json.loads(s) for s in path.read_text().splitlines()]
        assert len(samples)>=390
        cpu=[s['host_cpu_fraction'] for s in samples if s.get('host_cpu_fraction') is not None]
        def sectors(sample):
            return next((list(map(int,[v[5],v[9]])) for line in sample['diskstats'].splitlines() if len(v:=line.split())>9 and v[2]=='vda'),[0,0])
        start,end=sectors(samples[0]),sectors(samples[-1])
        resource_rows.append(dict(workload=kind,size=size,repeat=repeat,server_samples=len(samples),server_host_cpu_mean=sum(cpu)/len(cpu),server_host_cpu_peak=max(cpu),server_host_memory_peak=max(s['host_memory_fraction'] for s in samples),database_container_memory_peak_MiB=max(s['container_memory_bytes'] for s in samples)/1048576,database_connections_peak=max(s.get('database_connections',0) for s in samples),host_disk_read_MiB=max(0,end[0]-start[0])*512/1048576,host_disk_write_MiB=max(0,end[1]-start[1])*512/1048576,load_host_cpu_peak=point['maximum_load_cpu_fraction'],load_host_memory_peak=point['maximum_load_memory_fraction'],server_raw_sha256=sha(path)))
    write_csv('resource-summary.csv',resource_rows)
    controls=original['correctness_controls']
    write_json('correctness-controls.json',controls)
    coverage=[('F1','部分通过/错误语义失败','三次重启120确认写入无丢失；14次500、12传输失败；未测p95回归基线时间'),('F2','失败','三次占满15连接后约30秒返回500，静态端点仍200'),('F3','已测通过（限定场景）','瞬态超时/429/503、持续503五次进死信、查询降级均三重复；只针对所列输入'),('F4','边界验证通过/端到端覆盖有限','24次adapter观察；指令文字可留作未验证候选，无法改变scope/authority；不声称实际执行注入'),('F5','通过','真实进程死亡，默认30秒租约后替代worker接手，三次通过'),('F6','通过','三次默认30秒实际过期后，旧worker向量提交均被拒绝'),('F7','通过（冻结控制样本）','原生100并发相同幂等请求；异参同键409，重复记忆0'),('F8','通过（冻结控制样本）','原生20并发同revision修订，1成功19冲突，丢失更新0'),('F9','数据正确性通过/错误语义失败','16MiB独立测试盘真实53100；写500、读200、释放后写201；确认写入无丢失'),('F10','未测/配置约束','本轮要求固定腾讯单一向量型号，未执行换型号实验，不宣称通过'),('F11','未测','冻结B0没有指定的新迁移目标，未构造虚假业务迁移'),('F12','限定注入通过','应用now依赖±120秒六次成功；未改真实主机OS时钟，不等于多主机物理时钟漂移试验')]
    write_csv('fault-coverage.csv',[dict(id=i,status=s,evidence=e) for i,s,e in coverage])
    lines=['# 新配置B0聚合评测报告','',f'> 由 Codex 整理 · {now.isoformat()} · 业务 agent-memory@{baseline[:7]} · 收尾工具 {head[:7]}（含未提交修改）','',
           '**交付范围：已完成测量的汇总与覆盖结论。阶段2验收未通过，测量覆盖仍有明确缺口；未进入阶段3。**','',
           '本报告整理四组系统、各抽样数据集、直写和全链路结果、置信区间、人工校准、18轮公网测量与故障验证。失败结果不隐藏，未测项目不以0代替。已完成报告整理不等于所有指标通过或所有计划场景已执行。','',
           '## 配置与B0定义','',
           '- 业务源码固定B0@1e9d6f3；本轮配置B0-deepseek-v4-pro-kinfra-20261026-v1。此前混用模型的结果全部是“探索性，不计入B0”。',
           '- 答题与运行抽取均为官网deepseek-v4-pro，温度0、关闭思考，按已完成预检固定请求与响应型号标识；供应商内部权重快照无法独立验证。主裁判glm-5.2，备选minimax-m3来自TokenHub，均非DeepSeek厂商。',
           '- 运行向量为kinfra-text-embedding-0.6b原生1024维，新索引从本配置输入重新计算。凭据切换不更改型号；容量准备完成10万唯一虚构文本的原生向量。',
           '- O10未测：方舟无额度且明确禁止继续调用。旧方舟结果不构成新配置公平对照，不据此宣称腾讯优于方舟。',
           '- DeepSeek同时是金标准标注模型之一，答题与抽取与标注同厂商，可能使抽取类指标略偏高；两个厂商共同保留金标准已部分抵消。MiniMax交叉参照与MiniMax备选是同一个型号，不称独立。','',
           '## 样本与统计口径','',
           '冻结开发抽样65问题（含12个流程问题），四系统×两模式×三次共1560行，其中1272行真实质量样本、288行中文构造流程样本。未运行测试集，不是完整开发集、不是官方榜单分数。DuLeMon和ECD用于抽取/负样本，缺少答题问题时不伪造四系统问答成绩。','',
           '质量区间采用会话簇bootstrap1000，三次重复不当作三倍独立会话。分母、簇数和各指标均见CSV；空分母为未测/不适用。校准通过后保留原GLM标签分数，不用分层人工样本直接套统一系数修正整个人群。','',
           '## 四系统、各数据集与两模式','',
           'direct=显式直写；full=全链路抽取。系统为no-memory、full-context、naive-vector、system。chinese_queries_v2同时包含B类保留质量题和C类构造流程题：每组每模式18行质量、36行流程，分开报告，不合成总分。','',
           '| 数据/模式/系统 | 样本行 | E1 [95%CI] | RT1@10 [95%CI] | 最差题型（E1，并列保留） |','| --- | --- | --- | --- | --- |']
    for key,m in original['measurements'].items():
        e=estimate(m['values'].get('E1'))
        lines.append(f"| {key} | {m['rows']} | {e} | {estimate(m['values'].get('RT1@10'))} | {', '.join(original['worst_types'].get(key,[])) or '不适用'} |")
    lines+=['','表内样本行只计质量题；288行C类流程结果另存flow-only.json，不作质量证据。全量E1/RT1–RT6/证据覆盖等点估计和区间在metrics.csv；所有题型分层在by-type.csv，最差项分母在worst-types.csv；配对系统差及full-direct差在paired-comparisons.csv。','',
            '## 全链路检索为零的诊断','',
            '冻结B0缺少候选确认转active的公开路径。旧链路6640条记忆有证据映射但active为0；111个会话重复单元中2个无产出、109个被状态过滤。不能把候选被过滤与证据缺失、语义检索没召回混为一谈。restore仅恢复归档记忆，不能确认候选；没有偷偷改状态，确认后第二套测量为未测/不适用。缺陷B0-CANDIDATE-ACTIVATION-MISSING保留。','',
            '## QA300人工校准与稳定性','',
            '门槛：Cohen κ≥0.7或准确率≥90%。两位裁判总体达标；分层小样本结果仍需谨慎。','',
            '| 裁判 | 一致率 | κ | 裁判判对但人工判错/300 | 三次重复任一变化/100 |','| --- | --- | --- | --- | --- |']
    for name,m in qa['judge_models'].items():
        g=m['overall'];lines.append(f"| {name} | {g['accuracy']:.2%} | {g['kappa']:.4f} | {g['confusion']['judge1_human0']}/300 | {'3/100' if name=='glm-5.2' else '1/100'} |")
    lines+=['','完整混淆矩阵、分题型/系统一致率、最差层与条件区间见qa-calibration.json。人工理由和逐项标签不随报告交付。','',
            '## 抽取73条专项人工判定','',
            f"73行全对齐，原题/参考/答案未改。GLM一致率94.52%、κ0.8857；MiniMax95.89%、κ0.9148；43条有效性、30条覆盖分别达门槛。直接使用人工样本指标：精确率21/43=48.84%，95%会话簇区间[20.00%,72.22%]；召回率7/30=23.33%，区间[0,48.15%]；F1=0.3158。仅8会话三次抽样。",'',
            'EX5独立归属错误子标签及抽取专项重复稳定性不由这73条二元判定覆盖，不能用QA100×3替代。ECD8个已知负会话三次共误抽37候选；18/24会话重复单元有误抽，局限于客服负样本，不外推一般对话。','',
            '## 18轮独立主机公网测量','',
            'TX2发压；TX的PostgreSQL测试容器限制2CPU/3GiB/shm512MiB，API在TX宿主机运行、未单独设CPU/内存限额，不能将容器额度当整套服务额度。规模1万/10万、100租户、80%热租户，1QPS，每点1分钟预热+5分钟测量，三重复。两台均ap-shanghai，只证明跨公网独立主机，不证明跨地域。虚构32字符语料、精确原生向量；查询携带预计算向量，不能把接口测量当真实云端查询向量化耗时。Mac试验因资源超限作废，不合并。','',
            '| 接口 | 规模 | 测量请求 | 错误 | 错误比例 | 确认写入（含预热）/丢失 | 三次客户端p95均值 |','| --- | --- | --- | --- | --- | --- | --- |']
    for kind in ['search','write','context']:
        for size in [10000,100000]:
            a=[r for r in perf if r['workload']==kind and r['size']==size];n=sum(r['measured_requests'] for r in a);e=sum(r['errors'] for r in a)
            ack=f"{sum(r['confirmed_writes_including_warmup'] or 0 for r in a)}/{sum(r['confirmed_missing'] or 0 for r in a)}" if kind=='write' else '不适用'
            lines.append(f"| {kind} | {size} | {n} | {e} | {e/n:.2%} | {ack} | {sum(r['client_p95_ms'] for r in a)/3000:.2f}秒 |")
    lines+=['','write测量1805次零错误，含预热2165确认写入均在且对应入库任务完成；零观察错误不保证总体零风险。search和context未通过1QPS持续容量要求；每轮均有丢弃到达，不能宣称最大吞吐。','',
           'performance-trials.csv含18轮逐次延迟、错误、丢弃及完成队列耗时；performance-group-intervals.csv提供六组重复级区间（3轮、27种重采样，精度很低）。resource-summary.csv给两端CPU/内存、DB连接、宿主机磁盘IO摘要和原始采样SHA。宿主机统计含其他进程，不能独归本服务。队列耗时仅DB入队到完成，未计未完成任务/WAN可见性，不能替代客户端新鲜度。p95区间是各轮p95均值的区间，不是池化逐请求p95区间。未完成完整速率/租户数/近似索引网格。','',
            '## 故障与可靠性覆盖','',
            '| 编号 | 状态 | 证据与限制 |','| --- | --- | --- |']
    lines += [f'| {i} | {s} | {e} |' for i,s,e in coverage]
    lines+=['','## 备份、tokenizer和日志','',
            '- 100k全备484088060字节，39.14秒，Mac恢复9.40秒；全表行数/校验和、1000随机行、32检索、RLS/角色一致。源pgvector0.8.6、目标0.8.7差异保留。源初次64MiB共享内存不足失败，修正512MiB后核验通过；原失败不删除。',
            '- 官方DeepSeek-V4-Pro tokenizer固定修订与SHA见tokenizer.json，390上下文、8次官网usage文本差分核验均0。空上下文分母不造0。',
            '- SC4未通过：全部18轮应用异常日志中，取消查询的SQL参数带出完整虚构查询正文117次；首批六轮为58次，后续补测增加59次。所检查当前API密钥命中0次。不代表所有历史日志/外部收集器的总计。初期成功/422场景无泄漏不能替代此失败结论。',
            '- LC7只观察逻辑删除后正文残留等局部事实，不宣称已实现完整物理清除或备份删除。','',
            '## 失败案例与缺陷','',
            'failure-cases.json列20个实际失败ID、数据集/模式/系统/题型/原因码，不放原文、答案或人工理由。包括无历史基线不匹配、空召回、检索后答案不匹配等实际类别；这些是匿名案例索引，不是新编造示例。全部失败按reason_counts汇总，不能用个别例子替代全体。','',
            '优先缺陷：候选不能公开确认生效；检索/上下文严重超时和连接池等待；异常堆栈暴露查询正文；连接耗尽和磁盘满返回未分类500。只做B0观察，未擅自修复或进入阶段3。','',
            '## 资源与未完成项','',
            '原1560整组同配置恢复链路累计24459次实际HTTP尝试；失败重试保留，未知usage不当0。各角色汇总见resources.json。QA重复校准、官方tokenizer核验、容量向量准备等独立批次分别留证，不与主运行乱相加，也不据token数伪造费用账单。','',
            '完整66项指标逐项覆盖状态见metric-coverage.csv。“已测”仅表示在所列范围有数据，不等于通过；“局部观察”不能代替完整指标。除上述缺口外，nDCG、幻觉率、冗余/误拦等缺少适当独立金标准的指标也明确保留为未测，未用相似指标顶替。','',
            '剩余覆盖缺口包括：跨地域链路、完整多租户/速率/索引网格、EX5独立人工子标签、抽取专项重复稳定性、真实多主机时钟偏移、迁移期间流量、完整删除/备份清除及外部遥测收集器。F10受单一型号配置约束，F11缺指定迁移目标；这些不是已通过，不因本报告交付而自动消失。','',
            '**结论：当前B0不满足全面性能与安全验收。报告收尾与交付完成后仍保留上述缺陷及覆盖缺口，阶段3需负责人另行决定。**']
    lines.insert(lines.index('## 18轮独立主机公网测量'),f"抽取F1联合会话簇bootstrap95%区间为[{f1_ci[0]:.4f}, {f1_ci[1]:.4f}]，1000次重采样，种子42，详见extraction-F1-interval.json。\n")
    (output/'B0-report.md').write_text('\n'.join(lines)+'\n')
    write_json('resources.json',original['resources'])
    write_json('aggregate.json',{'generated_at':now.isoformat(),'baseline_commit':baseline,'harness_review_commit':head,'uncommitted':True,'report_document_finalized':True,'measurement_coverage_complete':False,'phase2_accepted':False,'stage3_started':False,'baseline_configuration_id':original['baseline_configuration_id'],'measurements':original['measurements'],'by_type':original['by_type'],'paired_comparisons':original['paired_comparisons'],'full_minus_direct':original['full_minus_direct'],'warning':'Historical evaluation_method strings describing uncalibrated scores are superseded by QA300 and extraction73 calibration in this bundle; numerical measurements unchanged. C-level flow rows are separate from B-level retained quality rows within chinese_queries_v2; flow rows are not quality evidence.'})
    # Numeric calibration snapshots are public aggregate inputs; no row-level labels are copied.
    sys.path.insert(0,str(ROOT/'scripts'));from b0_accounts import credential,ACCOUNTS
    secrets=[]
    for account in ACCOUNTS:
        try:secrets.append(credential(account)[2].encode())
        except (ValueError,KeyError,FileNotFoundError):pass
    for path in output.iterdir():
        raw=path.read_bytes();assert not any(s and s in raw for s in secrets), 'CONFIGURED_SECRET_IN_ARTIFACT'
        assert not any(key in raw for key in [b'"human_correct":',b'"human_reason":',b'"private_source":']), 'ROW_LEVEL_PRIVATE_FIELD_IN_ARTIFACT'
    manifest={'generated_at':now.isoformat(),'report_document_finalized':True,'measurement_coverage_complete':False,'phase2_accepted':False,'expected_tables':40,'total_functional_rows':1560,'quality_rows':1272,'flow_only_rows':288,'performance_trials':18,'source_aggregate_sha256':sha(BASE/'aggregate/report.json'),'generator_sha256':sha(Path(__file__)),'artifact_secret_scan_passed':True,'files':{p.name:sha(p) for p in output.iterdir()}}
    write_json('manifest.json',manifest)
    archive=output.with_suffix('.zip')
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for path in sorted(output.iterdir()):z.write(path,arcname=path.name)
    pointer=ROOT/'.local/phase2/b0/completion-20261028/final-report-artifact-private.json'
    pointer.write_text(json.dumps({'directory':str(output),'archive':str(archive),'archive_sha256':sha(archive),'generated_at':now.isoformat(),'sent':False},indent=2)+'\n');pointer.chmod(0o600)
    print(json.dumps({'report':str(output/'B0-report.md'),'archive':str(archive),'files':len(manifest['files'])+1,'metrics':len(measures),'by_type_metrics':len(types),'quality_tables':40,'performance_trials':18,'coverage_complete':False}))


if __name__=='__main__':main()
