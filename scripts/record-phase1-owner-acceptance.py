"""Record the explicit owner acceptance without changing historical handoffs."""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import subprocess
from zoneinfo import ZoneInfo


def main():
    target=Path('docs/evals/phase1-acceptance-current.json')
    if target.exists():
        raise ValueError('acceptance already recorded; preserve original decision')
    paths=['docs/evals/reliable-chinese-current.json','docs/evals/negative-conversations-current.json']
    memory,negative=[json.loads(Path(p).read_text()) for p in paths]
    assert memory['minimum_700_passed'] and negative['both_passed']
    report=Path('docs/reports/phase1-ecd180-confirmed-2026-10-23/report.json')
    record={'phase1_accepted':True,'owner_message_id':'om_x100b629f945d4ca8de645562ff5d2aa',
            'owner_decision':'验收','recorded_beijing':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
            'basis_report':str(report),'basis_report_sha256':hashlib.sha256(report.read_bytes()).hexdigest(),
            'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
            'reliable_memory_points':memory['accepted_union'],
            'individually_human_confirmed':memory['individually_human_confirmed'],
            'model_pool_only_not_individually_confirmed':memory['model_only_not_individually_confirmed'],
            'negative_conversations':negative['numerator'],'classifiable_conversations':negative['denominator'],
            'negative_fraction':negative['fraction'],'remaining_target_1500_gap':memory['gap_1500'],
            'phase2_started':False,'phase2_items_not_completed':['judge human calibration','ECD system false-extraction evaluation'],
            'historical_reports_unchanged':True,'labels_and_splits_unchanged':True,'model_calls':0}
    for p,data in zip(paths,[memory,negative],strict=True):
        data['phase1_accepted']=True
        data['acceptance_record']=str(target)
        Path(p).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
    target.write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n')
    with Path('docs/progress.md').open('a') as f:
        f.write(f"\n\n## {record['recorded_beijing'][:10]} 阶段1负责人验收（Codex记录）\n\n负责人消息 `{record['owner_message_id']}` 明确“验收”。已记录阶段1通过，当前可靠规模 {record['reliable_memory_points']}（逐条人工 {record['individually_human_confirmed']}，模型池采纳但未逐条人工 {record['model_pool_only_not_individually_confirmed']}）；确认负会话 {record['negative_conversations']}/{record['classifiable_conversations']}={record['negative_fraction']:.4%}，数量与占比闸门均过。当前状态与 `docs/evals/phase1-acceptance-current.json` 同步；验收前历史报告保留其原状态与来源，不改人工标签、切分或统计。1500目标差 {record['remaining_target_1500_gap']}，如实保留。阶段2未开始，裁判人工校准与ECD系统误抽评测未冒称完成。\n")
    print(json.dumps(record,ensure_ascii=False))


if __name__=='__main__':main()
