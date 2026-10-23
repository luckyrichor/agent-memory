"""Offline, evidence-bound adoption; no model calls and no inferred human labels."""
import csv
import json
import math
import platform
import re
import subprocess
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from agent_memory.evals.evidence_v3 import read_rows, sha
from agent_memory.evals.human_review import csv_text, digest
from agent_memory.evals.metrics import ratio

BASE = Path('.local/phase1/round3/new-accounts-v1')
OLD = Path('.local/phase1/round3/temporal-v1')
INC = BASE / 'increment-batches-v6'
PACK = INC / 'audit72'
PRIVATE = BASE / 'blind-adoption-v1'
OUT = Path('docs/reports/phase1-blind-adoption-2026-10-23')
SUBMITTED = Path('.local/dulemon72-increment-human-reviewed.csv')
PLAN = Path('docs/plans/2026-10-22-agent-memory-interview-plan-v3.md')


def load(p):
    return json.loads(p.read_text())


def write(p, data):
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')


def rows_by_id(p):
    rows = read_rows(p)
    result = {r['item_id']: r for r in rows}
    assert len(result) == len(rows), f'duplicate ID: {p}'
    return result


def lines(p, rows):
    p.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows))


def validate_return(template, submitted, mapping, items):
    """Keep blank owner reasons exactly; this task explicitly accepts keep72/discard0."""
    with submitted.open(encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        assert reader.fieldnames == ['item_id', 'conversation_id', 'subject', 'candidate', 'source', 'record_sha256', 'human_label', 'human_reason']
        returned = list(reader)
    assert len(returned) == len(template) == len(mapping)
    projected = []
    for expected, actual in zip(template, returned, strict=True):
        for key in ('item_id', 'conversation_id', 'subject', 'candidate', 'source'):
            assert actual[key] == csv_text(expected[key]), f'frozen field changed: {key}'
        assert actual['record_sha256'] == digest(expected), 'record digest changed'
        original = mapping[expected['item_id']]
        assert {k:v for k,v in expected.items() if not k.startswith('human_') and k != 'item_id'} == {k:v for k,v in items[original].items() if k != 'item_id'}
        assert actual['human_label'] in ('keep', 'discard', 'uncertain')
        projected.append({'item_id': original, 'label': actual['human_label'], 'reason': actual['human_reason']})
    assert len({r['item_id'] for r in projected}) == len(projected)
    return projected


def main():
    assert sha(PLAN) == '06ad7319525c6b0f4eb7333c981b094dd1ed6ec41ae2e5ea1b46009306389418'
    assert sha(SUBMITTED) == '3be624714c49f62191fc9bcfc83be009f5520922aaa51475faeba8ec1a408552'
    manifest = load(PACK / 'manifest.json')
    for name, value in manifest['files'].items():
        assert sha(PACK / name) == value
    for path, value in manifest['inputs'].items():
        assert sha(Path(path)) == value
    protected = {}
    for p in (BASE/'ecd-unchanged-hashes.json', Path('.local/phase1/round3/followup/protected-hashes.json')):
        protected.update(load(p))
    for path, value in protected.items():
        assert sha(Path(path)) == value, 'protected evidence changed'
    frozen = load(INC/'report.json')
    assert frozen['complete'] and frozen['supplement_complete'] and not frozen['blocked']
    items = rows_by_id(INC/'audit-items.jsonl')
    left, right = (rows_by_id(INC/name) for name in ('audit-left.jsonl', 'audit-right.jsonl'))
    assert items.keys() == left.keys() == right.keys()
    joint = {k for k in items if left[k]['label'] == right[k]['label'] == 'keep'}
    assert len(joint) == frozen['joint_keep']
    mapping = load(PACK/'opaque-map-private.json')
    template = read_rows(PACK/'audit-blind.jsonl')
    assert set(mapping.values()) <= joint
    excluded = {r['item_id'] for r in read_rows(OLD/'human-all-original.jsonl')}
    split = load(Path('.local/phase1/round3/evidence-v3-replacement/split-private.json'))
    excluded.update(split['development']); excluded.update(split['final'])
    excluded.update(load(OLD/'transport-probe-excluded-ids.json')['ids'])
    assert not joint & excluded
    projected = validate_return(template, SUBMITTED, mapping, items)
    errors = sum(r['label'] != 'keep' for r in projected)
    assert errors <= manifest['maximum_errors'], 'audit failed; do not adopt model pool'
    clusters = Counter(items[r['item_id']]['conversation_id'] for r in projected)
    correct = Counter(items[r['item_id']]['conversation_id'] for r in projected if r['label'] == 'keep')
    precision = ratio([(correct[c], clusters[c]) for c in sorted(clusters)]).to_dict()
    assert precision['n'] == manifest['conversations']
    rejected = {r['item_id'] for r in projected if r['label'] != 'keep'}
    new = joint - rejected
    old = rows_by_id(BASE/'adopted-old-pool-private.jsonl')
    previous_human = rows_by_id(OLD/'human-positive-items.jsonl')
    previous_labels = rows_by_id(OLD/'human-positive-labels.jsonl')
    assert previous_labels.keys() == previous_human.keys()
    assert all(r['label'] == 'keep' for r in previous_labels.values())
    human = {**previous_human, **{r['item_id']:items[r['item_id']] for r in projected if r['label']=='keep'}}
    human_labels = {**previous_labels, **{r['item_id']:r for r in projected if r['label']=='keep'}}
    union = dict(old)
    for pool in (human, {k:items[k] for k in new}):
        for key, value in pool.items():
            assert key not in union or union[key] == value, 'ID collision with different source'
            union[key] = value
    registry = load(INC/'batch-registry.json')
    provenance = {r['item_id']:r for r in read_rows(INC/'item-model-provenance-private.jsonl')}
    coverage = set()
    for batch in registry:
        path = Path(batch['path'])
        batch_items = read_rows(path/'items.jsonl')
        assert sha(path/'items.jsonl') == load(path/'manifest.json')['items_sha256']
        coverage.update(r['conversation_id'] for r in batch_items)
        assert len({r['conversation_id'] for r in batch_items}) == batch['conversations']
    positive_conversations = {r['conversation_id'] for r in union.values()}
    ecd = load(Path('docs/evals/ecd-human-current.json'))
    ecd_sets = {name:{r['conversation_id'] for r in read_rows(OLD/f'ecd-owner/{name}-private.jsonl')} for name in ('negative','positive','uncertain')}
    assert all(not ecd_sets[a] & ecd_sets[b] for a,b in [('negative','positive'),('negative','uncertain'),('positive','uncertain')])
    assert not positive_conversations & set.union(*ecd_sets.values())
    negatives = ecd_sets['negative']
    labeled = positive_conversations | negatives | ecd_sets['positive']
    negative_fraction = len(negatives) / len(labeled)
    needed_negative = max(0, math.ceil((.30*len(labeled)-len(negatives))/.70))
    gates = {'denominator_definition':'distinct adopted-positive DuLeMon conversation IDs union reviewed ECD positive/negative IDs; ECD uncertain excluded',
             'dulemon_positive_conversations':len(positive_conversations), 'ecd_negative':len(negatives), 'ecd_positive':len(ecd_sets['positive']), 'ecd_uncertain_excluded':len(ecd_sets['uncertain']),
             'classified_conversations':len(labeled), 'minimum_conversations':300, 'count_passed':len(labeled)>=300,
             'negative_numerator':len(negatives), 'negative_denominator':len(labeled), 'negative_fraction':negative_fraction, 'minimum_negative_fraction':.30, 'negative_fraction_passed':negative_fraction>=.30,
             'additional_confirmed_negative_conversations_needed_if_other_counts_fixed':needed_negative,
             'both_passed':len(labeled)>=300 and negative_fraction>=.30,
             'complete_conversation_gold_coverage_confirmed':False,
             'scope':'classified evidence union only; not a frozen exhaustive full-conversation extraction gold registry',
             'increment_source_coverage_conversations_not_gold_negatives':len(coverage),
             'complete_negative_labels_required':True, 'candidate_discards_inferred_negative':0}
    PRIVATE.mkdir(parents=True, exist_ok=True, mode=0o700); OUT.mkdir(parents=True, exist_ok=True)
    lines(PRIVATE/'human-labels-projection-private.jsonl', projected)
    lines(PRIVATE/'human-positive-items-private.jsonl', [human[k] for k in sorted(human)])
    lines(PRIVATE/'human-positive-labels-private.jsonl', [human_labels[k] for k in sorted(human_labels)])
    lines(PRIVATE/'adopted-new-pool-private.jsonl', [items[k] for k in sorted(new)])
    lines(PRIVATE/'accepted-union-private.jsonl', [union[k] for k in sorted(union)])
    prov = [{'item_id':k, 'individually_human_confirmed':k in human, 'old_audited_pool':k in old, 'new_audited_pool':k in new,
             'new_batch_evidence':provenance.get(k) if k in new else None} for k in sorted(union)]
    write(PRIVATE/'accepted-provenance-private.json', prov)
    write(PRIVATE/'classified-conversations-private.json', {'dulemon_positive':sorted(positive_conversations), **{k:sorted(v) for k,v in ecd_sets.items()}})
    counts = {'individually_human_confirmed':len(human), 'previous_human':len(previous_human), 'new_human':len(human)-len(previous_human),
              'old_audited_model_pool':len(old), 'new_pool_adopted':len(new), 'human_old_overlap':len(human.keys() & old.keys()),
              'human_new_overlap':len(human.keys() & new), 'old_new_overlap':len(old.keys() & new),
              'old_model_only_not_individually_confirmed':len(old.keys()-human.keys()), 'new_model_only_not_individually_confirmed':len(new-human.keys()),
              'model_only_not_individually_confirmed':len(union.keys()-human.keys()), 'accepted_union':len(union),
              'minimum_700_passed':len(union)>=700, 'gap_1500':max(0,1500-len(union))}
    code = subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
    dirty = bool(subprocess.check_output(['git','status','--porcelain'],text=True).strip())
    log = PRIVATE/'check.log'
    validation = {'completed':False}
    if log.exists():
        text = log.read_text(); match = re.search(r'(\d+) passed in ([\d.]+)s', text)
        validation = {'completed': bool(match and 'All checks passed!' in text and 'no issues found' in text and 'tenant_leaks=0 deleted_memory_hits=0' in text), 'pytest_passed':int(match[1]) if match else None, 'pytest_seconds':float(match[2]) if match else None, 'log_sha256':sha(log)}
        (OUT/'validation.log').write_text(text)
    report = {'created_beijing':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(), 'source_commit':code, 'uncommitted_changes_at_generation':dirty,
              'script_sha256':sha(Path(__file__)), 'plan':str(PLAN), 'plan_sha256':sha(PLAN), 'submitted_sha256':sha(SUBMITTED), 'submitted_bytes':SUBMITTED.stat().st_size,
              'template_and_inputs_verified':True, 'blank_human_reasons_preserved':sum(not r['reason'] for r in projected),
              'audit':{'labels':dict(Counter(r['label'] for r in projected)), 'errors':errors, 'maximum_errors':manifest['maximum_errors'], 'passed':True, 'precision':precision, 'bootstrap':1000, 'bootstrap_seed':42, 'sample_seed':manifest['seed']},
              'counts':counts, 'negative_gates':gates, 'new_model_batches':[{k:b[k] for k in ('batch','models','conversations','candidates','joint_keep')} for b in registry],
              'inputs_sha256':{**manifest['inputs'], **{str(PACK/k):v for k,v in manifest['files'].items()}, str(INC/'report.json'):sha(INC/'report.json'), str(INC/'batch-registry.json'):sha(INC/'batch-registry.json'), **{str(BASE/k):sha(BASE/k) for k in ('adopted-old-pool-private.jsonl','accepted-base-union-private.jsonl','accepted-base-provenance-private.json')}},
              'private_outputs_sha256':{str(p):sha(p) for p in PRIVATE.glob('*private.*')}, 'protected_hashes_verified':protected,
              'environment':{'platform':platform.platform(), 'python':platform.python_version(), 'hostname':platform.node()},
              'judge_pools_sha256':sha(Path('docs/evals/judge-pools-new-accounts-v1.json')),
              'validation_controls':load(PRIVATE/'validation-controls.json') if (PRIVATE/'validation-controls.json').exists() else None,
              'uv_lock_sha256':sha(Path('uv.lock')), 'metrics_sha256':sha(Path('src/agent_memory/evals/metrics.py')),
              'model_calls_this_task':0, 'new_model_tokens_this_task':0, 'formal_scores_allowed':False, 'phase1_accepted':False, 'validation':validation}
    write(OUT/'report.json', report)
    write(Path('docs/evals/reliable-chinese-current.json'), {'basis':'old-owner-approved-and-new-blind-audit-approved-union-human', **counts, 'old_temporal_screen_applied':False, 'new_temporal_screen_applied':True, 'phase1_accepted':False, 'report':str(OUT/'report.json'), 'items_sha256':sha(PRIVATE/'accepted-union-private.jsonl'), 'provenance_sha256':sha(PRIVATE/'accepted-provenance-private.json')})
    write(Path('docs/evals/human-confirmed-current.json'), {'basis':'owner-individually-confirmed-original-id-union', 'confirmed_positive_points':len(human), 'whole_joint_pool_individually_confirmed':False, 'labels':{'path':str(PRIVATE/'human-positive-labels-private.jsonl'),'sha256':sha(PRIVATE/'human-positive-labels-private.jsonl')}, 'items':{'path':str(PRIVATE/'human-positive-items-private.jsonl'),'sha256':sha(PRIVATE/'human-positive-items-private.jsonl')}, 'new_owner_return_sha256':sha(SUBMITTED), 'phase1_accepted':False})
    p=precision; c=counts; g=gates
    prior = Path('docs/reports/phase1-round3-new-accounts-2026-10-22/delivery.md').read_text()
    ecd_section = prior.split('## ECD负样本小金标准\n',1)[1].split('## 裁判池：',1)[0].strip()
    delivery = f'''# agent-memory 阶段1新增盲审采纳收尾

由 Codex 生成；具体模型版本未核实。生成北京时间：{report['created_beijing']}。分析源码 `{code}`；生成时有未提交修改：{dirty}。生成器 SHA256 `{report['script_sha256']}`；完整环境、证据哈希见 report.json。阶段1仍未验收，不进入阶段2。

## 版本与执行范围

完整重读最新版方案 `{PLAN}`，SHA256 `{sha(PLAN)}`，与上一轮v3原件一致，无新方案附件。历史原件不改。本次用户任务覆盖原方案旧数量/角色示例：旧池扣已知人工错误后采纳且不应用时效性筛选；新增池临时不得keep；按实际厂商排除裁判；仅离线采纳，不调用模型、不再增量。既有v2/v3差异保留在上一轮 plan-diff.patch。

## 新增盲审结果

附件 {report['submitted_bytes']} 字节，SHA256 `{sha(SUBMITTED)}`。冻结CSV、JSONL、原ID映射与输入哈希全部核对；逐行顺序、全部非人工字段、source原JSON、record_sha256和映射原记录相符。人工理由空白 {report['blank_human_reasons_preserved']} 行原样保留，不编理由。

真实负责人核对 {p['denominator']:.0f} 条，keep {report['audit']['labels'].get('keep',0)}、discard {report['audit']['labels'].get('discard',0)}、错误 {errors}，上限 {manifest['maximum_errors']}，通过。抽样种子 {manifest['seed']}，{p['n']} 会话；先按会话聚合正确/总条数，再用 metrics.ratio 做 {report['audit']['bootstrap']} 次成对会话重采样，种子 {report['audit']['bootstrap_seed']}。样本精度 {p['value']:.4%}，95%普通百分位区间 [{p['ci95'][0]:.4%}, {p['ci95'][1]:.4%}]。全部样本成功使 bootstrap 区间退化；不证明总体精度100%，不能保证整池没有未知错误，不额外扣未发生的预留错误。没有使用旧超几何区间。

## 原ID去重采纳

旧池 {c['old_audited_model_pool']}、新增盲审通过模型池 {c['new_pool_adopted']}、全部逐条人工正例 {c['individually_human_confirmed']}（此前 {c['previous_human']} + 本次新增 {c['new_human']}）；人工与旧池重叠 {c['human_old_overlap']}，与新增池重叠 {c['human_new_overlap']}，旧新池重叠 {c['old_new_overlap']}。最终去重 **{c['accepted_union']} 记忆点**，最低700规模门通过={c['minimum_700_passed']}，距1500目标缺 {c['gap_1500']}。

逐条人工确认 **{c['individually_human_confirmed']}**；仅模型标注、抽检通过整池采纳而未逐条人工确认 **{c['model_only_not_individually_confirmed']}**（旧 {c['old_model_only_not_individually_confirmed']}、新 {c['new_model_only_not_individually_confirmed']}）。旧池不应用时效性筛选，新增池应用；仅规模去重合并，两者质量指标不混算。新池的既有分批模型及输入规模见report.json，实际标注厂商DeepSeek/Tencent；历史失败与半批不接入。私有标签、来源、批次证据和逐项provenance只在.local，当前公开清单已更新；旧文件不覆盖。

## 完整会话与负会话双闸门

以采纳记忆所属 DuLeMon 去重会话 {g['dulemon_positive_conversations']} + ECD已确认负会话 {g['ecd_negative']} + ECD已确认正会话 {g['ecd_positive']} 为可分类会话分母，共 **{g['classified_conversations']}**。来源前缀与ID去重且跨语料无交集；ECD不确定 {g['ecd_uncertain_excluded']} 单列，不计正负或比例分母。DuLeMon正会话仅证明至少一个已采纳记忆点，不能声称已穷尽全会话应记内容。

会话数量 ≥{g['minimum_conversations']}：**{g['count_passed']}**。确认负会话占比 **{g['negative_numerator']}/{g['negative_denominator']} = {g['negative_fraction']:.4%}**，≥{g['minimum_negative_fraction']:.0%}：**{g['negative_fraction_passed']}**。双闸门共同通过：**{g['both_passed']}**。若其他会话不变，需另确认至少 **{g['additional_confirmed_negative_conversations_needed_if_other_counts_fixed']}** 个完整负会话；新增后分母也随之增加。此为证据合并核算，不是总体负会话流行率。

新增标注源覆盖 {g['increment_source_coverage_conversations_not_gold_negatives']} 个会话，只表示输入覆盖；共同discard、没有共同keep或单候选discard均未推断为负金标，新增推断负标签为 {g['candidate_discards_inferred_negative']}。当前分母是已采纳正会话与已核验负会话的证据并集，尚不是已冻结且逐会话穷尽标注的完整抽取集；数量门仅在这一明确口径下达到，完整会话金标准覆盖仍未确认。完整负会话仍需负责人核对“整段没有任何应记内容”；本次不生成新人工答案、不催审或启动补量。未证明完整抽取金标覆盖的会话不能冒充全部逐会话标注完成。

## ECD负样本小金标准

{ecd_section}

## 裁判与未完成

旧/新增表技术池沿用GLM5.2主、MiMo-V2.6-Flash和MiniMax-M3备，详情 docs/evals/judge-pools-new-accounts-v1.json。实际标注DeepSeek/Tencent、答题ByteDance均排除。仅技术预检通过，owner calibration未完成，formal_scores_allowed=false。本次不运行正式评分。

阶段1仍未验收：负会话占比闸门未通过；完整会话级抽取金标准仍待补足/确认；裁判人工校准、ECD系统误抽评测未做；历史双标κ等未完成项不能用本次抽检通过代替。合成三类题仍只作流程验证，旧阶段1报告其他未完成项保留。仅最低记忆点规模达标不等于阶段验收。

## 复现与检查

运行 `uv run python scripts/adopt-increment-blind-audit-v1.py`，全量门 `bash scripts/check.sh`；在tx当前checkout执行。全门结果：{json.dumps(validation,ensure_ascii=False)}；完整日志 validation.log（存在时）。本次新增模型调用 {report['model_calls_this_task']}，新增模型token {report['new_model_tokens_this_task']}；无新增模型费用。对照为上一轮未采纳状态；本次不是系统质量提升实验，无新正式判分或失败案例抽样。
'''
    (OUT/'delivery.md').write_text(delivery)
    progress = Path('docs/progress.md'); marker='\n## 阶段1新增盲审采纳收尾（自动生成）\n'
    original=progress.read_text().split(marker)[0]
    progress.write_text(original+marker+f"\n新增盲审 {p['numerator']:.0f}/{p['denominator']:.0f}，{p['n']}会话；会话聚类bootstrap95%区间{p['ci95']}。采纳新增{len(new)}，原ID去重总{len(union)}；逐条人工{len(human)}、模型整池未逐条人工{len(union)-len(human)}。完整会话证据核算{len(labeled)}，负会话{len(negatives)}/{len(labeled)}={negative_fraction:.4%}，双闸门通过={g['both_passed']}。阶段1未验收；本次无模型调用。全门completed={validation['completed']}。报告：[{OUT.name}](reports/{OUT.name}/delivery.md)。\n")
    devlog = Path('docs/devlog/2026-10-23-phase1-blind-adoption.md')
    devlog.write_text(f'''# 阶段1新增盲审采纳开发记录

由Codex编写；具体模型版本未核实。负责人提供目标、阈值及真实人工CSV，本次未声称独立人工复核或验收。

任务：最新版方案第5、11、13、14节；精确接入新增盲审并核算采纳及负会话闸门。完整任务依据为本次用户一次性延时任务，未重新调用模型或补量。

设计：保留历史冻结文件，新脚本离线核验哈希与逐行非人工字段，再从不透明ID映射回原ID。人工理由按附件保留空白；程序不填写人工理由。采用原会话聚类ratio，而非旧超几何方法；缺少完整会话标签时明确列缺口。

实现：scripts/adopt-increment-blind-audit-v1.py生成本轮私有标签/provenance、公开报告、current清单及进展。全部记忆正文、会话ID与ECD原文留.local。检查CSV原source、精确摘要、顺序、标签范围；哈希保护旧ECD和模板；并集遇同ID异内容即失败。未改业务架构、依赖、数据库或生产服务。

依赖：Python {platform.python_version()}、标准库和现有metrics.ratio；环境指纹、锁文件及脚本SHA见report.json。数据来自非合成DuLeMon及ECD；旧会话切分不变；ECD仍为AI草稿加人工确认。实际历史标注组合逐批保留于report.json，未将跨模型部分标签拼接。

运行：uv run python scripts/adopt-increment-blind-audit-v1.py；bash scripts/check.sh。抽样种子{manifest['seed']}，bootstrap种子{report['audit']['bootstrap_seed']}。本次模型调用{report['model_calls_this_task']}、新增token{report['new_model_tokens_this_task']}。模型费用无新增，普通CPU检查消耗本机资源。

结果：逐条人工{len(human)}，采纳并集{len(union)}，模型未逐条人工{len(union)-len(human)}；具体精度、区间、会话闸门见[本次报告](../reports/{OUT.name}/delivery.md)。全门completed={validation['completed']}，原日志和耗时由报告脚本读取。独立篡改检查验证source变化、摘要变化、重复行及非法标签均拒绝，真实附件保持不变，结果由validation-controls.json记录。初次使用系统python入口不可用，改用项目uv run python正常；全量门未失败。本轮没有修改标注提示词或最终集。

风险：全成功bootstrap区间退化不能证明总体无误；双闸门未通过，完整会话级金标准仍未确认，人工裁判校准未做。阶段1未验收，不进入阶段2，不自动生成新负标签。来源提交{code}；生成时未提交修改={dirty}，最终交付提交由delivery-receipt.json另行记录。负责人本次仅确认盲审结果，未代签阶段验收。
''')
    index=Path('docs/devlog/INDEX.md'); entry=f'- [{devlog.stem}]({devlog.name})'
    if entry not in index.read_text():
        index.write_text(index.read_text().rstrip()+'\n\n'+entry+'\n')
    print(json.dumps({'counts':counts,'negative_gates':gates,'validation':validation},ensure_ascii=False))


if __name__ == '__main__':
    main()
