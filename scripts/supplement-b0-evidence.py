"""Reconcile current B0 evidence and recovery costs; no model calls or business writes."""
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from agent_memory.evals.b0 import clustered_paired
from agent_memory.evals.metrics import latency, ratio

REPO = Path(__file__).resolve().parents[1]
RUN = REPO / '.local/phase2/b0/frozen-deepseek-20261026-v1/recovery-run-2'
OUT = REPO / 'docs/reports/phase2-b0-evidence-supplement-2026-10-27'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path):
    return json.loads(path.read_text())


def jsonl(path):
    return [json.loads(s) for s in path.read_text().splitlines() if s.strip()]


def lineage(root, seen=None):
    seen = set() if seen is None else seen
    root = root.resolve()
    if root in seen:
        return []
    seen.add(root)
    manifest = load(root / 'run-manifest.json')
    assert manifest['baseline_commit'] == '1e9d6f3b25b58c85792344000d7e1b5a71a79737'
    assert manifest['config']['baseline_configuration_id'] == 'B0-deepseek-v4-pro-kinfra-20261026-v1'
    result = [root]
    for parent in manifest['config'].get('resume_roots', []):
        result.extend(lineage(REPO / parent, seen))
    return result


def strings(body):
    """Count actual outgoing text fields, not JSON keys, metadata or HTTP credentials."""
    result = []
    for message in body.get('messages', []):
        content = message.get('content')
        if isinstance(content, str):
            result.append(content)
        elif isinstance(content, list):
            result.extend(part['text'] for part in content if isinstance(part, dict) and isinstance(part.get('text'), str))
    value = body.get('input')
    if isinstance(value, str):
        result.append(value)
    elif isinstance(value, list):
        result.extend(s for s in value if isinstance(s, str))
    return result


def model_resources(roots):
    by_role = defaultdict(list)
    provenance = []
    egress = defaultdict(Counter)
    for root in roots:
        usage = jsonl(root / 'usage.jsonl')
        provenance.append({'run': str(root.relative_to(REPO)), 'usage_sha256': sha(root / 'usage.jsonl'),
            'manifest_sha256': sha(root / 'run-manifest.json'), 'ledger_rows': len(usage)})
        for record in usage:
            if record.get('cache_hit') or record.get('fixture_only') or record.get('new_http_call') is False:
                continue
            by_role[record['role']].append(record)
            values = egress[record['provider']]
            request = root / f"calls/{record['call_id']:07d}-request-private.json"
            if not request.exists():
                values['missing_request_body_attempts'] += 1
                continue
            parts = strings(load(request))
            count, size = len(parts), sum(len(s.encode('utf-8')) for s in parts)
            values['attempts_with_request_body'] += 1
            values['attempted_text_strings'] += count
            values['attempted_text_utf8_bytes'] += size
            # Any HTTP response establishes arrival at the provider; transport failures are unknown.
            if isinstance(record.get('http'), int):
                values['responded_attempts'] += 1
                values['responded_text_strings'] += count
                values['responded_text_utf8_bytes'] += size
            else:
                values['transport_unknown_attempts'] += 1
    costs = {}
    for role, records in sorted(by_role.items()):
        known = [r for r in records if r.get('usage')]
        costs[role] = {'post_attempts': len(records), 'known_usage_responses': len(known),
            'usage_unknown': len(records) - len(known),
            'input_tokens': sum(r['usage'].get('prompt_tokens', 0) for r in known),
            'output_tokens': sum(r['usage'].get('completion_tokens', 0) for r in known),
            'total_tokens': sum(r['usage'].get('total_tokens', 0) for r in known),
            'latency_seconds': latency([r['seconds'] for r in records]),
            'attempted_wire_json_bytes': sum(r['input_bytes'] for r in records),
            'scope': 'all new HTTP attempts across identical-config recovery lineage; no evaluation-row replays double counted; failures/retries included; calibration/preflights excluded'}
    return costs, dict(egress), provenance


def ecd_false_extraction(imports, roots):
    dataset = load(REPO / 'docs/baselines/b0/datasets-v1.json')['ecd_negative']
    data_path = REPO / dataset['path']
    assert sha(data_path) == dataset['sha256'] and dataset['dev_memory_points'] == 0
    negatives = {r['conversation_id'] for r in jsonl(data_path)}
    selected = [r for r in imports if r['dataset'] == 'ecd_negative' and r['mode'] == 'full']
    mapping_hashes = []
    groups = defaultdict(lambda: [0, 0, 0, 0])
    repeats = defaultdict(lambda: [0, 0, 0, 0])
    for row in selected:
        assert row['conversation_id'] in negatives
        key = [row['dataset'], row['conversation_id'], 'full', row['repeat']]
        name = hashlib.sha256(json.dumps(key, sort_keys=True, ensure_ascii=False).encode()).hexdigest() + '.json'
        candidates = [root / 'mappings' / name for root in roots if (root / 'mappings' / name).exists()]
        if not candidates:
            raise ValueError('missing authoritative extraction evidence')
        mapping = load(candidates[0])
        assert len(mapping) == row['memories'] and row['active_memories'] == 0
        mapping_hashes.append({'opaque_unit_hash': name[:-5], 'sha256': sha(candidates[0])})
        count = len(mapping)
        for target in (groups[row['conversation_id']], repeats[row['repeat']]):
            target[0] += count
            target[1] += count
            target[2] += int(count > 0)
            target[3] += 1
    return {'metric': 'EX4', 'dataset': 'ecd_negative', 'mode': 'full', 'system': 'system',
        'data_level': dataset['data_level'], 'source_sha256': dataset['sha256'],
        'memory_error_ratio': ratio([(a, b) for a, b, _, _ in groups.values()]).to_dict(),
        'conversation_false_extraction_ratio': ratio([(c, d) for _, _, c, d in groups.values()]).to_dict(),
        'unique_conversations': len(groups), 'conversation_repeat_units': len(selected),
        'repeat_counts': {str(k): {'false_candidates': v[0], 'all_candidates': v[1],
            'nonempty_conversations': v[2], 'conversations': v[3]} for k, v in sorted(repeats.items())},
        'mapping_hashes': mapping_hashes,
        'method': 'All candidates output by full-chain extraction in owner-confirmed no-memory conversations are false extractions. Candidate outputs, not active retrieval; no semantic judge and no model calls. Three repeats clustered by original conversation.',
        'baseline': 'frozen B0 candidate output (no-memory system does not extract; full-context/raw vector chunks are not extracted memories)',
        'limitation': '8-conversation fixed dev sample of282 confirmed ECD negatives, NOT full282. ECD is customer-service domain, not general conversation. AI draft+human confirmation; all errors bootstrap can degenerate, no proof of population100%. Not EX1/EX2/EX5 general semantic calibration.'}


def controls_index(controls):
    grouped = defaultdict(list)
    for row in controls.get('observations', []):
        grouped[row['id']].append(row)
    result = {}
    for mid, records in grouped.items():
        result[mid] = {'observations': records, 'status': 'measured synthetic control only',
            'data_level': 'C synthetic functional fixture; not semantic quality or PF'}
        if mid == 'LC5':
            result[mid]['estimate'] = records[0]['estimate']
        elif mid == 'LC4':
            result[mid]['estimate'] = ratio([(r['leak_queries'], r['denominator_queries'])
                for r in records if r.get('setup_valid')]).to_dict()
        elif mid in ('SC1', 'SC3', 'RT10'):
            field = {'SC1': 'cross_tenant_successes', 'SC3': 'unauthorized_successes', 'RT10': 'forbidden_returned'}[mid]
            result[mid]['returned_or_bypass_count'] = sum(r[field] for r in records if r.get(field) is not None)
            result[mid]['attempts_or_scope_cases'] = sum(r['scale'] for r in records)
            result[mid]['ci95'] = None
            result[mid]['ci_reason'] = 'observed count in finite fixed fixtures, not a population failure probability'
        elif mid == 'LC7':
            result[mid]['status'] = 'partial measured: body residue observed, vectors/events/backups not fully covered'
            result[mid]['retained_body_versions_per_repeat'] = [r['retained_body_versions'] for r in records]
        elif mid in ('RL1', 'RL2'):
            field = 'all_consistent' if mid == 'RL1' else 'lost_update_count'
            result[mid]['repeat_outcomes'] = [r[field] for r in records]
    return result


def question_subset_metrics(rows):
    """Use native preference labels and verified session-oracle inputs, never infer new gold."""
    def clustered(items):
        groups = defaultdict(list)
        for row in items:
            groups[row['conversation_id']].append(row)
        return ratio([(sum(r['judge_correct'] for r in values), len(values))
            for values in groups.values()]).to_dict()
    preferences = defaultdict(list)
    for row in rows:
        if row['category'] in ('single-session-preference', 'preference') and not row['flow_only']:
            preferences[row['dataset'], row['mode'], row['system']].append(row)
    e5 = {'/'.join(k): {'estimate': clustered(v), 'rows': len(v),
        'unique_questions': len({r['question_id'] for r in v}),
        'method': 'fixed native/existing preference-question subset; original GLM answer correctness against preference gold, not proof of causal memory use',
        'baseline': 'same questions no-memory/full-context/naive-vector/system',
        'limitation': 'small dev subset; no new question selection, gold or preference tags; no general personalization claim'}
        for k, v in sorted(preferences.items())}
    manifest = load(REPO / 'docs/baselines/b0/datasets-v1.json')['longmemeval_oracle']
    source = REPO / manifest['path']
    assert sha(source) == manifest['sha256']
    source_rows = {r['conversation_id']: r for r in jsonl(source)}
    oracle = [r for r in rows if r['dataset'] == 'longmemeval_oracle' and r['system'] == 'full-context'
              and not source_rows[r['conversation_id']]['questions'][0]['abstention']]
    for row in oracle:
        conv = source_rows[row['conversation_id']]
        assert conv['metadata']['evidence_level'] == 'session'
        relevant = set(conv['questions'][0]['relevant'])
        assert relevant and all(d['session_id'] in relevant for d in conv['documents'])
        assert not row.get('full_context_truncated')
    e6 = {}
    for mode in ('direct', 'full'):
        reference = [r for r in oracle if r['mode'] == mode]
        ids = {q['conversation_id'] for q in reference}
        oracle_labels = {(r['conversation_id'], r['question_id'], r['repeat']): r['judge_correct'] for r in reference}
        system_labels = {(r['conversation_id'], r['question_id'], r['repeat']): r['judge_correct'] for r in rows
            if r['dataset'] == 'longmemeval_oracle' and r['mode'] == mode and r['system'] == 'system'
            and r['conversation_id'] in ids}
        e6[mode] = {'estimate': clustered(reference), 'rows': len(reference),
            'unique_questions': len({r['question_id'] for r in reference}),
            'dataset_sha256': manifest['sha256'],
            'method': 'original public session-oracle input; all source sessions verified relevant; raw full-context baseline, no truncation; abstention excluded because no positive oracle evidence',
            'oracle_granularity': 'supporting sessions, not manually isolated answer-bearing spans',
            'oracle_minus_system_paired_gap': clustered_paired(system_labels, oracle_labels),
            'comparison': {system: clustered([r for r in rows if r['dataset'] == 'longmemeval_oracle'
                and r['mode'] == mode and r['system'] == system
                and r['conversation_id'] in {q['conversation_id'] for q in reference}])
                for system in ('no-memory', 'naive-vector', 'system')},
            'limitation': 'empirical same-model session-oracle reference, not a guaranteed mathematical upper bound; no comparison to independently sampled longmemeval_s questions'}
    return e5, e6


def main():
    roots = lineage(RUN)
    report_path = RUN / 'aggregate/report.json'
    report = load(report_path)
    assert report['human_calibration_received'] and report['owner_judge_calibration']['self_consistency_complete']
    costs, egress, provenance = model_resources(roots)
    e5, e6 = question_subset_metrics(load(RUN / 'graded-results-private.json'))
    controls = controls_index(load(RUN / 'correctness-observations.json'))
    queue_path = OUT / 'queue-controls.json'
    queue = load(queue_path) if queue_path.exists() else None
    if queue:
        assert queue['baseline_commit'] == report['run_manifest']['baseline_commit']
        for mid in ('RL3', 'RL4'):
            controls[mid] = queue[mid]
    ecd = ecd_false_extraction(jsonl(RUN / 'imports-private.jsonl'), roots)
    ledger = []
    calibrated = report['owner_judge_calibration']['judge_models']['glm-5.2']['overall']['adoptable_on_this_calibration']
    for entry in report['metric_coverage']:
        item = dict(entry)
        mid = item['id']
        if mid in controls:
            item.update(measurement_status=controls[mid]['status'], evidence='control_observations/' + mid)
            if 'estimate' in controls[mid]:
                item.update(controls[mid]['estimate'])
        elif mid == 'EX4':
            item.update(measurement_status='partial measured: ECD negative development sample only', evidence='ecd_false_extraction')
        elif mid == 'EX8':
            item.update(measurement_status='measured by dataset; three repeats clustered by original conversation', evidence='B0/extraction_failure_rates_EX8')
        elif mid == 'SC8':
            item.update(measurement_status='measured outgoing text attempts with provider-response bounds; not proof of international transfer', evidence='provider_egress')
        elif mid in ('RT1', 'RT2', 'RT3', 'RT6', 'E1'):
            item.update(measurement_status='measured frozen dev sample in per-dataset/mode/system tables; GLM owner calibrated' if calibrated else 'uncalibrated', evidence='B0/measurements')
        elif mid == 'RT5':
            item.update(measurement_status='partial measured by type: RT1/RT2/RT3; RT4 lacks graded memory relevance', evidence='B0/by_type')
        elif mid == 'E2':
            item.update(measurement_status='measured paired comparisons per dataset and mode; no mixed-domain total', evidence='B0/paired_comparisons')
        elif mid == 'E5':
            item.update(measurement_status='partial measured: frozen preference-labeled question subsets only', evidence='preference_question_metrics')
        elif mid == 'E6':
            item.update(measurement_status='partial measured: verified session-oracle, non-abstention questions only', evidence='session_oracle_reference')
        ledger.append(item)
    now = datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()
    supplement = {'created_beijing': now, 'source_script_sha256': sha(Path(__file__)),
        'baseline_commit': report['run_manifest']['baseline_commit'],
        'baseline_configuration_id': report['baseline_configuration_id'],
        'no_new_model_calls': True, 'business_code_unchanged': True,
        'recovery_lineage': provenance, 'all_recovery_resources': costs,
        'provider_egress': egress, 'control_observations': controls, 'ecd_false_extraction': ecd,
        'queue_controls': queue,
        'preference_question_metrics': e5, 'session_oracle_reference': e6,
        'metric_coverage': ledger,
        'coverage_status_counts': dict(Counter(r['measurement_status'] for r in ledger)),
        'resource_limitation': 'Known token sums exclude unknown usage, not imputed zero. Calibration/preflights separate. API attempt latency is not single-event end-to-end EX9 or PF; no per-system E3 attribution inferred.',
        'sc8_definition': 'UTF8 bytes of messages[].content and embedding input strings per actual attempt, repeated sends counted repeatedly. JSON keys/headers not included; network failures give unknown-delivery upper bound. Counts are external-provider transmission, not a geographic border claim.',
        'phase2_accepted': False, 'stage3_started': False,
        'delivery': 'deferred until complete as owner requested; this partial supplement is local only'}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'evidence-supplement.json').write_text(json.dumps(supplement, ensure_ascii=False, indent=2) + '\n')
    text = ['# B0现有证据补齐（局部进展，非完成报告）', '', now, '',
        '仅重算冻结新B0已有数据，无新增模型调用、不改业务、数据或切分；依负责人要求不发送未完成聚合版。', '',
        '## ECD系统误抽', '', json.dumps(ecd, ensure_ascii=False, indent=2), '',
        '## 全部同配置恢复链资源', '', json.dumps(costs, ensure_ascii=False, indent=2), '',
        '## 对外文本发送量', '', supplement['sc8_definition'], json.dumps(egress, ensure_ascii=False, indent=2), '',
        '## 偏好题与会话级oracle参考', '', json.dumps({'E5': e5, 'E6': e6}, ensure_ascii=False, indent=2), '',
        '## 队列控制', '', json.dumps(queue, ensure_ascii=False, indent=2), '',
        '## 已有观测登记更正', '', 'LC4/LC5/RL1/RL2/RT10/SC1/SC3已有本轮证据，LC7仅正文残留局部验证；此前目录占位不代表无观测。完整原始结构见JSON。', '',
        '## 指标覆盖', '', '| 指标 | 状态 | 证据 |', '|---|---|---|']
    text += [f"| {r['id']} | {r['measurement_status']} | {r.get('evidence', '')} |" for r in ledger]
    text += ['', '仍待：EX语义输出人工对应/校准、真正目标tokenizer与预算实验、故障/备份演练、日志全量覆盖、独立跨地域PF等。已有观测只覆盖本轮样本与有限构造控制，不填伪造0、不伪装全量完成。']
    (OUT / 'evidence-supplement.md').write_text('\n'.join(text) + '\n')
    report['metric_coverage'] = ledger
    report['classification'] = 'new frozen B0 configuration; answer judge human-calibrated; full metric coverage/PF incomplete'
    report['current_measurement_state'] = 'local evidence supplementation in progress; full aggregate delivery deferred'
    report['historical_execution_status_note'] = 'execution_status is the original benchmark-process stop state; owner calibration and later evidence are recorded in their own subsequent sections'
    report['resource_scope_previous'] = 'previous resources showed only final recovery; superseded by all identical-configuration lineage HTTP attempts'
    report['resources'] = costs
    report['evidence_supplement'] = {'path': str(OUT.relative_to(REPO) / 'evidence-supplement.json'), 'sha256': sha(OUT / 'evidence-supplement.json')}
    report['ecd_false_extraction'] = ecd
    report['provider_egress'] = egress
    report['preference_question_metrics'] = e5
    report['session_oracle_reference'] = e6
    report['queue_controls'] = queue
    report['formal_quality_scores_allowed'] = calibrated
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    report_path.chmod(0o600)
    print(json.dumps({'lineage_runs': len(roots), 'actual_http_attempts': sum(v['post_attempts'] for v in costs.values()),
        'ecd_false_extraction': ecd['memory_error_ratio'], 'ecd_conversation_rate': ecd['conversation_false_extraction_ratio'],
        'control_ids': sorted(controls), 'aggregate_sent': False}, ensure_ascii=False))


if __name__ == '__main__':
    main()
