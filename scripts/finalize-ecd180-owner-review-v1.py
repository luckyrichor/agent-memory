"""Intake owner ECD180 answers and publish aggregate-only phase1 handoff."""
import csv
from collections import Counter
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess
from zoneinfo import ZoneInfo

from agent_memory.evals.human_review import digest

ROOT=Path('.local/phase1/round3/ecd180-review-v1')
PRIVATE=ROOT/'owner-final'
OUT=Path('docs/reports/phase1-ecd180-confirmed-2026-10-23')
SUBMITTED=Path('.local/ecd180-human-labeled-final.csv')
TEMPLATE=ROOT/'sample/ecd180-preparation.csv'
HUMAN=('human_memories','human_no_memories','human_reason')
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
read=lambda p:json.loads(Path(p).read_text())


def rows(path):
    with path.open(encoding='utf-8-sig',newline='') as f:
        reader=csv.DictReader(f)
        return reader.fieldnames,list(reader)


def validate(columns, original, submitted):
    if columns!=['conversation_id','stratum','split','source','record_sha256',*HUMAN]:
        raise ValueError('unexpected review columns')
    before={r['conversation_id']:r for r in original}
    after={r['conversation_id']:r for r in submitted}
    if len(before)!=len(original) or len(after)!=len(submitted) or before.keys()!=after.keys():
        raise ValueError('duplicate or changed review ID coverage')
    classified=[]
    for cid,row in after.items():
        if list(row)!=columns:raise ValueError('review column mismatch')
        if any(row[k]!=before[cid][k] for k in columns if k not in HUMAN):
            raise ValueError('frozen field changed')
        reference={k:before[cid][k] for k in columns if k!='record_sha256'}
        reference['source']=json.loads(reference['source'])
        if digest(reference)!=row['record_sha256']:raise ValueError('frozen record digest mismatch')
        memories=row['human_memories'].strip();negative=row['human_no_memories'].strip().lower()
        if negative not in ('','true','false'):raise ValueError('invalid negative boolean')
        if negative=='true' and memories:raise ValueError('contradictory human answers')
        label='positive' if memories else ('negative' if negative=='true' else 'uncertain')
        classified.append({**row,'classification':label})
    return classified


def main():
    columns,original=rows(TEMPLATE);submitted_columns,submitted=rows(SUBMITTED)
    assert columns==submitted_columns
    classified=validate(columns,original,submitted)
    manifest=read(ROOT/'sample/manifest.json')
    assert sha(TEMPLATE)==manifest['private_csv_sha256']
    for path,h in manifest['protected_files_sha256'].items():assert sha(path)==h
    old_split=read('.local/phase1/chinese-expansion-v2/ecd/split.json')
    extended=read(ROOT/'sample/split-extended-private.json')
    assert sha(ROOT/'sample/split-extended-private.json')==manifest['extended_split_sha256']
    split_map={cid:side for side,ids in extended.items() for cid in ids}
    assert len(split_map)==sum(map(len,extended.values()))
    for side,ids in old_split.items():assert extended[side][:len(ids)]==ids
    assert all(split_map[r['conversation_id']]==r['split'] for r in classified)
    ids={r['conversation_id'] for r in classified};old_ids={cid for seq in old_split.values() for cid in seq}
    assert not ids&old_ids
    assert ids==split_map.keys()-old_ids
    counts=Counter(r['classification'] for r in classified)
    changes=Counter(r['classification'] for r in classified if '人工修改' in r['human_reason'])
    assert counts=={'negative':174,'positive':6} and sum(changes.values())==4
    # These are owner-provided expectations, verified against the actual attachment, not generated labels.
    previous=read('.local/phase1/round3/new-accounts-v1/blind-adoption-v1/classified-conversations-private.json')
    new_negative={r['conversation_id'] for r in classified if r['classification']=='negative'}
    new_positive={r['conversation_id'] for r in classified if r['classification']=='positive'}
    new_uncertain={r['conversation_id'] for r in classified if r['classification']=='uncertain'}
    old_negative=set(previous['negative']);old_positive=set(previous['positive']);du=set(previous['dulemon_positive'])
    assert not ids&(old_negative|old_positive|du|set(previous['uncertain']))
    negative=old_negative|new_negative;positive=old_positive|du|new_positive
    assert not negative&positive
    total=negative|positive;n=len(negative);d=len(total)
    frozen=read('docs/evals/reliable-chinese-current.json')
    protected={p:sha(p) for p in ['docs/evals/reliable-chinese-current.json','docs/evals/human-confirmed-current.json','docs/evals/ecd-human-current.json']}
    plan='docs/plans/2026-10-22-agent-memory-interview-plan-v3.md'
    prior=read('docs/reports/phase1-ecd180-fresh-preparation-2026-10-23/report.json')
    assert sha(plan)==prior['plan_sha256']
    log=(ROOT/'confirmed-check.log').read_text();match=re.search(r'(\d+) passed in ([\d.]+)s',log)
    assert match and 'All checks passed!' in log and 'no issues found' in log
    assert 'tenant_leaks=0 deleted_memory_hits=0' in log
    PRIVATE.mkdir(parents=True,exist_ok=True,mode=0o700)
    for label in ('positive','negative','uncertain'):
        p=PRIVATE/(label+'-private.jsonl')
        p.write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in classified if r['classification']==label));p.chmod(0o600)
    private_universe={**previous,'negative':sorted(negative),'positive':sorted(old_positive|new_positive),
                      'uncertain':sorted(set(previous['uncertain'])|new_uncertain)}
    target=PRIVATE/'classified-conversations-private.json'
    target.write_text(json.dumps(private_universe,indent=2)+'\n');target.chmod(0o600)
    ecd={'source':'ECD180','annotation_method':'AI 草稿加人工确认','independent_human_annotation':False,
         'counts':{k:counts[k] for k in ('negative','positive','uncertain')},'conversations':len(classified),
         'manual_change_marker_count':sum(changes.values()),'manual_change_classifications':dict(changes),
         'agent_modified_owner_labels':False,'submitted_sha256':sha(SUBMITTED),'template_sha256':sha(TEMPLATE),
         'actual_attachment_filename':'ecd180-human-labeled.csv','owner_referred_filename':'ecd180-human-labeled-final.csv',
         'owner_message_id':'om_x100b629f8cd6c8b0ddff05b215cb9ef',
         'attachment_message_id':'om_x100b629f8f5920acdefb86f8b83452b',
         'raw_private_only':True,'frozen_fields_and_record_hashes_verified':True,'old_splits_unchanged':True,
         'new_split_verified':True,'split_counts':dict(Counter(r['split'] for r in classified)),
         'source_domain':'customer service; not representative of general dialogue',
         'positive_conversations_are_not_additional_memory_point_count':True}
    gate={'numerator':n,'denominator':d,'fraction':n/d,'required_negative_fraction':.3,
          'minimum_classifiable_conversations':300,'count_passed':d>=300,'fraction_passed':10*n>=3*d,
          'both_passed':d>=300 and 10*n>=3*d,'uncertain_excluded':len(private_universe['uncertain']),
          'formula':f'({len(old_negative)}+{len(new_negative)})/({len(old_negative|old_positive|du)}+{len(new_negative)}+{len(new_positive)})',
          'source_rows':[
              {'source':'DuLeMon','negative':0,'positive':len(du),'uncertain_excluded':0,'annotation_method':'AI 草稿加人工确认（模型候选双标，抽检通过整池采纳；非逐条人工确认）'},
              {'source':'ECD 旧120','negative':len(old_negative),'positive':len(old_positive),'uncertain_excluded':len(previous['uncertain']),'annotation_method':'AI 草稿加人工确认'},
              {'source':'ECD 新180','negative':len(new_negative),'positive':len(new_positive),'uncertain_excluded':len(new_uncertain),'annotation_method':'AI 草稿加人工确认'}],
          'denominator_scope':'deduplicated adopted-positive DuLeMon conversations and human-confirmed classifiable ECD conversations; not all raw/model-input conversations',
          'ecd_total_negative':len(negative),'dulemon_total_negative':0,
          'candidate_discards_inferred_negative':0,'phase1_accepted':False,'phase2_started':False,
          'report':str(OUT/'report.json')}
    source=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
    report={'created_beijing':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),'source_commit':source,
            'source_dirty':bool(subprocess.check_output(['git','status','--porcelain'],text=True).strip()),
            'plan':plan,'plan_sha256':sha(plan),'same_plan_as_previous_handoff':True,
            'plan_differences':['Owner authorized additional random ECD180 beyond original small 100-150 target; old120 retained',
                                'Actual ECD annotation provenance is AI draft plus human confirmation, including owner corrections, not independent human labeling',
                                'Owner assigns judge human calibration and ECD system false-extraction evaluation to phase2; neither is a phase1 remaining item'],
            'intake':ecd,'negative_gate':gate,'reliable_memory_points':frozen,
            'audit':prior['audit'],'model_calls':0,'owner_labels_rewritten':0,
            'protected_registries_sha256':protected,'all_protected_inputs_unchanged':True,
            'phase1_minimum_scale_and_negative_gates_met':frozen['minimum_700_passed'] and gate['both_passed'],
            'phase1_accepted':False,'phase2_started':False,
            'remaining_phase1':['owner final acceptance; no remaining quantitative gate in the owner-defined scope'],
            'phase2_scope_only':['judge human calibration','ECD system false-extraction evaluation'],
            'validation':{'pytest':int(match[1]),'pytest_seconds':float(match[2]),'ruff':True,'strict_mypy':True,'foundation_8_of_8':True,
                          'log_sha256':sha(ROOT/'confirmed-check.log')}}
    OUT.mkdir(parents=True,exist_ok=True)
    Path('docs/evals/ecd180-human-current.json').write_text(json.dumps(ecd,ensure_ascii=False,indent=2)+'\n')
    Path('docs/evals/negative-conversations-current.json').write_text(json.dumps(gate,ensure_ascii=False,indent=2)+'\n')
    (OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    (OUT/'validation.log').write_text(log)
    table='\n'.join(f"| {r['source']} | {r['negative']} | {r['positive']} | {r['uncertain_excluded']} | {r['annotation_method']} |" for r in gate['source_rows'])
    cp=report['audit']['clopper_pearson_ci95']
    text=f'''# 阶段1交接：ECD新增人工确认与负会话双闸门

> 🤖 由 Codex 生成 · {report['created_beijing'][:10]} · 来源 agent-memory@{source[:12]} · 工具 lark-cli profile codex

生成时存在未提交修改：{report['source_dirty']}；本次报告与注册表另行提交。先前报告及其创建来源保留，本次只追加ECD180回填核验、比例与阶段1收尾状态。

## 结论

冻结公式 **{gate['formula']}={n}/{d}={n/d:.4%}**。完整负会话占比 ≥30%：{gate['fraction_passed']}；可分类会话数 ≥{gate['minimum_classifiable_conversations']}：{gate['count_passed']}。双闸门均通过。

真实中文记忆点仍为 {frozen['accepted_union']}，其中逐条人工确认 {frozen['individually_human_confirmed']}，抽检通过整池采纳、未逐条人工确认 {frozen['model_only_not_individually_confirmed']}。旧池 {frozen['old_audited_model_pool']}、新增池 {frozen['new_pool_adopted']} 与全部人工正例按原 item_id 去重，保底700已满足，距目标1500仍差 {frozen['gap_1500']}。ECD有应记的会话不自动增加记忆点规模。

负责人定义的阶段1最低规模与负样本量化门均已满足，**待负责人最终验收**。本次不自动开始阶段2。

## 按来源的完整会话计数

| 来源 | 无应记/负会话 | 有应记/正会话 | 不确定（排除） | 来源标记 |
| --- | --- | --- | --- | --- |
{table}

合计负 {n}、正 {len(positive)}、不确定 {gate['uncertain_excluded']}；可分类分母 {d}。负样本来源分别为 DuLeMon {gate['dulemon_total_negative']}、ECD {gate['ecd_total_negative']}。ECD是客服领域，不代表一般对话；混合比例仅说明当前评测集组成，不推断一般对话负例流行率。DuLeMon正会话表示至少有一个已采纳记忆点，并非全会话应记内容穷尽标注；没有共同keep或单候选discard均不推定完整负会话。

## 人工确认来源与改判

本轮 {len(classified)} 段：无应记 {counts['negative']}、有应记 {counts['positive']}、不确定 {counts['uncertain']}。均按“AI 草稿加人工确认”记录，不写人工独立标注。理由栏“人工修改”标记 {sum(changes.values())} 条，最终分类分布 `{dict(changes)}`；原草稿说明和最终人工内容保持附件原样，助手改写标签 {report['owner_labels_rewritten']} 条。这些改判不是额外新增会话，也不另扣总数。附件未标修改的其他行只能称未标修改，不据此推断草稿准确率；未对原始AI草稿逐字另行比对。

附件实际文件名为 `{ecd['actual_attachment_filename']}`，负责人正文称 `{ecd['owner_referred_filename']}`；按同一附件消息及内容识别，服务器以正文文件名保存。附件 SHA256 `{ecd['submitted_sha256']}`，冻结模板 SHA256 `{ecd['template_sha256']}`。

## 冻结字段、哈希与切分核验

原八列、会话ID全覆盖且唯一；除人工三栏外，stratum、split、逐轮source与record_sha256逐字段完全匹配模板。每条record_sha256依原规范重新计算，共 {len(classified)} 条通过。回填顺序不作为校验依据，按conversation_id对应。新旧会话不重叠；新增切分 `{ecd['split_counts']}` 与私有扩展切分逐ID一致，原400切分的列表前缀与归属保持不变。旧120模板及回填、全部保护文件与旧注册表哈希未变。原文、人工记忆内容和理由仅保留服务器私有目录，公开报告和Git只放方法、计数与哈希。

本次模型调用 {report['model_calls']}。源ECD的匹配回复标签不是记忆正负标签，仍只以负责人完整会话确认分类。新不确定排除正负及比例分母；既有 {gate['uncertain_excluded']} 条不确定继续单列。

## 方案版本与差异

执行 `{plan}`，SHA256 `{report['plan_sha256']}`，与前次核验版本一致。负责人已批准追加全新180段，超过原方案100–150段小金标的初始范围；原120保留。实际来源为AI草稿加人工确认，包含负责人改判，不能沿用原方案“直接人工标注”表述冒称独立人工。旧池不应用时效性筛选，新增池执行时效性判断，既有口径和采纳规模未变。

按负责人本次明确范围，裁判人工校准、ECD系统误抽评测属于阶段2，不列为阶段1未完成项，也未声称已完成。目标1500未达到但不是阶段1保底700的阻塞门；如实保留差距，不加新质量门。

## 新盲审区间沿用与验证

新增池此前独立盲审 {report['audit']['successes']}/{report['audit']['trials']}，会话级聚类bootstrap区间 `{report['audit']['conversation_bootstrap_ci95']}`（全成功退化）；补充Clopper–Pearson双侧95%区间 [{cp[0]:.4%}, {cp[1]:.4%}]。二项区间假定条目独立，不是聚类校正、不证明整池零未知错误。本次只接入ECD人工回填，未重跑或修改已冻结盲审。

全门 pytest {report['validation']['pytest']} passed in {report['validation']['pytest_seconds']}s；ruff、strict mypy、foundation8/8通过，见validation.log。复现：`uv run python scripts/finalize-ecd180-owner-review-v1.py`（需服务器私有原附件与冻结输入）。所有计数由脚本读取附件并按ID去重生成。

阶段1剩余：负责人最终验收。阶段2尚未开始；阶段2事项未冒称已完成。
'''
    (OUT/'delivery.md').write_text(text)
    assert all(sha(p)==h for p,h in protected.items())
    print(json.dumps({'new_counts':dict(counts),'manual_changes':dict(changes),'negative_gate':gate,'phase1_minimum_gates_met':report['phase1_minimum_scale_and_negative_gates_met']},ensure_ascii=False))


if __name__=='__main__':main()
