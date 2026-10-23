"""ECD preparation handoff and supplementary exact binomial audit uncertainty.

Current confirmed labels and adoption registries remain unchanged; no model calls.
"""
from datetime import datetime
from pathlib import Path
import hashlib
import json
import platform
import re
import shutil
import subprocess
from zoneinfo import ZoneInfo

from agent_memory.evals.metrics import clopper_pearson

ROOT=Path('.local/phase1/round3/ecd180-review-v1')
OUT=Path('docs/reports/phase1-ecd180-preparation-2026-10-23')
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
read=lambda p:json.loads(Path(p).read_text())


def main():
    previous=read('docs/reports/phase1-blind-adoption-2026-10-23/report.json')
    frozen=read('docs/evals/reliable-chinese-current.json')
    ecd=read('docs/evals/ecd-human-current.json')
    classified=read('.local/phase1/round3/new-accounts-v1/blind-adoption-v1/classified-conversations-private.json')
    if set(classified['negative']) & set(classified['positive']):raise ValueError('positive/negative conversation overlap')
    negative=set(classified['negative']);positive=set(classified['positive'])|set(classified['dulemon_positive']);total=negative|positive
    dulemon_positive={cid for cid in positive if cid.startswith('dulemon-')}
    # Validate actual source assignments rather than silently inferring a label from absent keep items.
    assert len(dulemon_positive)==previous['negative_gates']['dulemon_positive_conversations']
    ecd_negative={cid for cid in negative if cid.startswith('ecd:')}
    dulemon_negative={cid for cid in negative if cid.startswith('dulemon-')}
    ecd_positive={cid for cid in positive if cid.startswith('ecd:')}
    assert ecd_negative|dulemon_negative==negative and ecd_positive|dulemon_positive==positive
    assert len(ecd_negative)==ecd['counts']['negative'] and len(ecd_positive)==ecd['counts']['positive']
    p=previous['audit']['precision'];successes=int(p['numerator']);trials=int(p['denominator'])
    assert p['numerator']==successes and p['denominator']==trials
    cp=clopper_pearson(successes,trials);assert cp is not None
    plan=Path(previous['plan']);same_plan=sha(plan)==previous['plan_sha256']
    sample_path=ROOT/'sample/manifest.json';prepared=read(sample_path) if sample_path.exists() else None
    log=(ROOT/'check.log').read_text();match=re.search(r'(\d+) passed in ([\d.]+)s',log)
    assert match and 'All checks passed!' in log and 'no issues found' in log
    assert 'tenant_leaks=0 deleted_memory_hits=0' in log
    n=len(negative);d=len(total)
    needed=next(k for k in range(10000) if 10*(n+k)>=3*(d+k))
    projection=[]
    for uncertain in (0,5,20):
        classified_new=180-uncertain
        required=max(0,(3*(d+classified_new)+9)//10-n)
        projection.append({'new_uncertain':uncertain,'new_classifiable':classified_new,
                           'minimum_new_negative':required,'minimum_new_positive_or_negative_denominator':d+classified_new})
    code=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
    report={'created_beijing':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),'source_commit':code,
            'source_dirty':bool(subprocess.check_output(['git','status','--porcelain'],text=True).strip()),
            'plan':str(plan),'plan_sha256':sha(plan),'same_plan_as_previous_handoff':same_plan,
            'owner_task_message':'om_x100b629f797834b0df841804501f188',
            'plan_execution_difference':['Original ECD small reference target 100-150; owner now asks an additional independent random 180 preparation, original 120 unchanged',
                'Add item-level exact binomial interval as supplement, not a replacement for frozen conversation bootstrap or an added pass threshold',
                'Owner identifies only negative-session fraction as remaining phase1 gate; no new gate introduced'],
            'audit':{'successes':successes,'trials':trials,'precision':successes/trials,'conversation_clusters':p['n'],
                     'conversation_bootstrap_ci95':p['ci95'],'bootstrap_resamples':previous['audit']['bootstrap'],
                     'bootstrap_seed':previous['audit']['bootstrap_seed'],'clopper_pearson_ci95':cp,
                     'clopper_pearson_method':'two-sided equal-tailed exact binomial; binomial-tail inversion; all-success lower=(0.025)^(1/n), upper=1',
                     'clopper_pearson_assumptions':'independent Bernoulli item observations, no cluster adjustment or finite-population correction; supplementary only',
                     'reference':'https://www.itl.nist.gov/div898/handbook/prc/section2/prc241.htm'},
            'confirmed_sources':{'DuLeMon':{'negative':len(dulemon_negative),'positive':len(dulemon_positive)},
                                 'ECD':{'negative':len(ecd_negative),'positive':len(ecd_positive),'uncertain_excluded':ecd['counts']['uncertain'],
                                        'annotation_method':ecd['annotation_method'],'domain':'customer service, not representative of general dialogue'}},
            'negative_gate':{'numerator':n,'denominator':d,'fraction':n/d,'required_fraction':.3,'passed':10*n>=3*d,
                             'count_300_passed':d>=300,'additional_negative_only_needed':needed,
                             'pending_new_classifications_counted':0,
                             'after_owner_confirmation_formula':'(confirmed_old_negative + new_negative)/(confirmed_old_classifiable + new_negative + new_positive); new_uncertain excluded',
                             'all_new_180_negative_scenario':(n+180)/(d+180),'scenario_not_observed':True,'scenarios':projection},
            'reliable_memory_points':frozen['accepted_union'],'new_manual_preparation':prepared,
            'preparation_status':'exported; waiting owner confirmation of labels' if prepared else 'awaiting owner decision: truly fresh source vs unreviewed historical pool and split-extension authorization',
            'protected_current_registry_sha256':{p:sha(p) for p in ['docs/evals/reliable-chinese-current.json','docs/evals/human-confirmed-current.json','docs/evals/ecd-human-current.json']},
            'model_calls':0,'new_model_tokens':0,'model_cost':0,'inferred_new_labels':0,'existing_labels_changed':False,
            'ecd_raw_private_only':True,'new_180_adopted':False,'phase1_accepted':False,'phase2_started':False,
            'gates':{'pytest_passed':int(match[1]),'pytest_seconds':float(match[2]),'ruff':True,'strict_mypy':True,'foundation_8_of_8':True,'log_sha256':sha(ROOT/'check.log')},
            'environment':{'python':platform.python_version(),'platform':platform.platform()},
            'remaining':['owner to label the new 180 full conversations; uncertainty not counted as positive or negative',
                         'recalculate and pass negative-session share only from confirmed labels; no assumed ECD negative prevalence',
                         'owner phase1 acceptance required; no stage2 or model execution in this task']}
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    shutil.copyfile(ROOT/'check.log',OUT/'validation.log')
    if prepared:
        prep=f"已导出 {prepared['conversations']} 段预备 CSV，种子 {prepared['seed']}，候选总体 {prepared['sampling_population']}，切分分布 `{prepared['split_counts']}`，旧人工审核重叠 {prepared['old_human_review_overlap']}，以前模型输入重叠 {prepared['all_previous_model_source_overlap']}。沿用原表八列 `{', '.join(prepared['columns'])}`；人工三栏全部空白，逐轮 JSON 原样保留，顺序随机打乱，stratum 固定为 simple_random_unstratified（抽样方法，不是信息类别），没有模型标签/参照/模型筛选。CSV SHA256 `{prepared['private_csv_sha256']}`，{prepared['private_csv_bytes']:,} 字节。原 120 表、其回填和原切分均未改动。"
    else:
        prep='预备 CSV 尚未导出：冻结切分覆盖的 400 段都曾做过模型标注，其中 120 段已人工核对，其余 280 段仅是未人工核对。若按“全新未用”取完整原库的新会话，需要追加新会话切分；若从剩余 280 段取，则可直接继承原切分，但不能称从未用过。已请求负责人明确这一口径，未擅自选，也未改变旧切分。'
    source_rows='\n'.join(f"| {name} | {r['negative']} | {r['positive']} | {r.get('uncertain_excluded','不从未审候选推断')} |" for name,r in report['confirmed_sources'].items())
    r=report
    text=f'''# 阶段1：ECD 180 段预备审核与盲审区间补充

> 🤖 由 Codex 生成 · {r['created_beijing'][:10]} · 来源 agent-memory@{code[:12]} · 工具 lark-cli profile codex

## 结论

真实中文记忆点 {r['reliable_memory_points']}，最低规模已满足，未改采纳池。当前确认负会话 {n}/{d}={n/d:.4%}，尚未达到 30%。本次只准备人工审核和补充区间，新增 180 段不预先计作正/负；阶段1尚未由负责人验收，不进入阶段2。模型调用 {r['model_calls']}、新增模型 token {r['new_model_tokens']}。

## 方案版本与出入

已完整重读 `{plan}`，SHA256 `{r['plan_sha256']}`；与上轮执行文件一致：{same_plan}。原作者和原文未改。文件写的 ECD 小参照规模是 100–150；本次按负责人新指令另备 180 段，旧 120 保留。Clopper–Pearson 是新增的补充说明，不替换冻结 bootstrap，不新设通过线。按负责人本次认定，阶段1收尾仅处理负会话占比；前报告提到的后续裁判校准等仍未自动完成，不在本次另增阶段1门槛。

## 180 段预备表

{prep}

ECD 原文许可不明，仅保留服务器私有审核文件，不进入 GitHub 或公开报告。客服对话不代表一般对话；源角色为匿名 source，不能按轮次奇偶编造客户/助手身份。ECD 的 1/0 是候选回复匹配标签，绝不能把 0 直接当成无应记内容的负会话。180 段由负责人核对后才能分类，不能套用旧 120 段的 90% 自动生成标签。

## 新盲审精度与两种区间

精度 {successes}/{trials}={successes/trials:.4%}；{p['n']} 个会话聚类，原方法 {previous['audit']['bootstrap']} 次 bootstrap、种子 {previous['audit']['bootstrap_seed']}，95%区间 [{p['ci95'][0]:.4%}, {p['ci95'][1]:.4%}]，全成功导致退化，不能证明总体精度 100%。

补充精确二项 Clopper–Pearson 双侧 95% 区间 **[{cp[0]:.4%}, {cp[1]:.4%}]**。全成功时下界为 `(0.025)^(1/{trials})`，上界为 1；一般情形用二项尾概率反演，测试以闭式边界、NIST 示例和尾概率核对。方法参考 [NIST exact binomial intervals](https://www.itl.nist.gov/div898/handbook/prc/section2/prc241.htm)。

该二项区间采用条目独立 Bernoulli 假设，不处理同会话相关性，也没有有限总体修正；因此只是解释退化 bootstrap 的补充，不是会话聚类校正区间，也不能当成整池无未知错误或真实精度必达95%的证明。原“错误不超过3/72”的通过结论和全部校验不变。

## 按来源核算负样本

| 来源 | 已确认完整负会话 | 可分类正会话 | 不确定/未审 |
| --- | --- | --- | --- |
{source_rows}

分母是已采纳正会话与已确认负会话的去重并集；单个候选 discard 或无共同 keep 均不推导整会话负标签。DuLeMon 正会话只证明至少一个采纳记忆点，不表示已穷尽全会话应记内容。ECD 既有标签为“{ecd['annotation_method']}”，不冒称人工独立标注；{ecd['counts']['uncertain']} 段不确定排除正负与比例分母。ECD 是客服领域，因此本混合比例仅用于当前评测集组成，不外推一般对话或真实线上流行率。

当前会话数 ≥300：{d>=300}；负占比 ≥30%：{r['negative_gate']['passed']}。若只新增确认负会话且其他不变，最少还需 {needed} 段。负责人确认本轮结果后，严格按 **(原确认负会话+新负会话)÷(原可分类会话+新负会话+新正会话)** 重算；新不确定单列排除。

仅作计划情景：若 180 段全部可分类，至少需其中 {projection[0]['minimum_new_negative']} 段确认负；若全部 180 都确认负，占比为 {(n+180)/(d+180):.4%}。这些不是实际标签、不是达标承诺，不计入当前比例。

## 检查、遗留与复现

全门 pytest {r['gates']['pytest_passed']} 项通过，ruff、strict mypy、foundation 8/8 通过；日志 validation.log。生成报告：`uv run python scripts/report-ecd180-review-v1.py`；生成预备 CSV 的脚本为 scripts/prepare-ecd180-review-v1.py，必须明确源池口径及负责人决定后运行。数据、切分和旧人工结果均不放宽，不调用任何模型。

未完成：180 段人工确认及之后的占比重算；负责人最终阶段1验收。当前比例不提前变化。ECD 原文与审核理由只在服务器私有目录；本报告和 GitHub 只放方法、计数、哈希，不含原文。
'''
    (OUT/'delivery.md').write_text(text)
    print(json.dumps({'CP95':cp,'current_negative_fraction':n/d,'prepared':bool(prepared),'tests':r['gates']['pytest_passed']}))


if __name__=='__main__':main()
