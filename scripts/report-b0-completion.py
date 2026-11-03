"""Assemble measured supplements without promoting incomplete work to final B0."""
from datetime import datetime
import argparse
import json
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT/'docs/reports/phase2-b0-completion-2026-10-28'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--record-handoff', action='store_true')
    args = parser.parse_args()
    measured = {}
    for name in ['tokenizer','recovery100k','worker-crash','provider-faults','provider-exhaustion','database-restart','log-leak-check','extraction-diagnostic-v2','extraction-owner-calibration','public-load','tx2-public-load','tx2-results-audit','tx2-extra-public-load','remaining-faults','search-degradation-verified','disk-full','extraction-boundaries']:
        path = PUBLIC/(name+'.json')
        if path.exists(): measured[name] = json.loads(path.read_text())
    data = {'generated_at':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
            'baseline_commit':'1e9d6f3b25b58c85792344000d7e1b5a71a79737',
            'phase2_accepted':False,'full_aggregate_ready':False,'measured':measured,
            'remaining':['Extraction-specific human semantic calibration for73 blinded items; QA300 calibration does not transfer to extraction matching.',
                         'Complete PF coverage and capacity interpretation; timed runs are not automatically accepted.',
                         'Remaining F1–F12 coverage and full pressure/fault logs; completed individual observations do not certify all reliability controls.'],
            'limitations':['DeepSeek is also one gold annotation vendor; same-vendor answer/extraction can slightly inflate extraction scores; joint retention by two vendors partly mitigates this.',
                           'No new Ark/O10 model comparison because Ark has no quota; previous mixed-model results remain exploratory outside new B0.',
                           'Capacity corpus is entirely fictional, real native vectors,100k unique32-character texts; it is not natural semantic benchmark quality or the full natural memory length distribution.',
                           'Mac was explicitly authorized as an independent load host; physical cross-region placement is not independently verified.',
                           'MiniMax cross-reference and MiniMax backup are the same model and are not independent.']}
    if 'extraction-owner-calibration' in measured:
        data['remaining'][0] = 'Extraction owner73 judgments validated and both judges pass by task. EX1/EX2/F1 sampled human metrics available; separate EX5 ownership sublabel calibration and extraction repeat stability remain uncovered.'
    (PUBLIC/'completion-status.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
    lines=['# B0补齐过程记录（未完成，不用于最终交付）','',f"更新：{data['generated_at']}",'',
           '业务版本B0@1e9d6f3；测量工具来自agent-memory@2fae08b及未提交修改。未进入阶段3。','',
           '| 项目 | 已核对结果 |','| --- | --- |']
    if 'tokenizer' in measured: lines.append('| 官方tokenizer | 390上下文；8次API usage文本差分核对均为0 |')
    if 'recovery100k' in measured:
        r=measured['recovery100k'];lines.append(f"| 100k跨Mac恢复 | {r['status']}；全表/1000随机行/32检索/角色RLS核对；环境差异见单项报告 |")
    if 'worker-crash' in measured:lines.append('| worker实际进程死亡 | 默认30秒租约，三次由替代worker接手；每版本向量1行 |')
    if 'provider-faults' in measured:lines.append('| 向量HTTP瞬态故障 | 超时/429/503各三次，退避后第二次成功；持续失败/死信仍待覆盖 |')
    if 'database-restart' in measured:lines.append('| 数据库重启 | 三次共120确认写入无丢失；14次HTTP500与12次传输失败，错误语义仍是缺陷 |')
    if 'log-leak-check' in measured:
        leak = measured['log-leak-check']
        if leak.get('public_pressure_complete_body_occurrences',0):
            lines.append(f"| 日志/链路 | 未通过：公网压测异常日志完整虚构查询正文命中{leak['public_pressure_complete_body_occurrences']}次；所检查API密钥命中0次；外部收集器仍未覆盖 |")
        else:
            lines.append('| 日志/链路 | 局部实测0标记/0密钥；全故障和压测覆盖未齐，不宣称SC4全覆盖通过 |')
    if 'tx2-results-audit' in measured:
        lines.append('| 独立公网发压 | 六轮已核验；1万条失败557/867、10万条869/888，1QPS容量未通过；两端同上海，不代表跨地域 |')
    lines.extend(['','待完成：','']+['- '+s for s in data['remaining']]+['','局限：','']+['- '+s for s in data['limitations']])
    (PUBLIC/'completion-progress.md').write_text('\n'.join(lines)+'\n')
    terminal_capacity = (measured.get('tx2-extra-public-load') or measured.get('tx2-public-load', {})).get('status') in (
        'measurements_complete','failed_requires_review','stopped_invalid_load_host_resources')
    if args.record_handoff or terminal_capacity:
        capacity = measured.get('tx2-extra-public-load') or measured.get('tx2-public-load', {})
        status = capacity.get('status','not_collected')
        points = len(capacity.get('points',[]))
        expected = capacity.get('expected_points',6)
        block = ('<!-- B0_CAPACITY_SEQUENCE_START -->\n'
                 f"- {data['generated_at']} TX2托管容量测量状态：{status}，已收集{points}/{expected}点；实际结果与有效性见docs/reports/phase2-b0-completion-2026-10-28/tx2-public-load.json。\n"
                 '- 本托管程序已尝试清理自有API与临时Nginx入口，接手者应核对服务和入口确已关闭；失败记录保留。\n'
                 '- 本记录不表示阶段2全部完成：抽取专项人工校准、其余PF/故障覆盖、跨地域链路等缺口仍须核对；完整报告未放行，未进入阶段3，Wiki按用户暂缓。\n'
                 '<!-- B0_CAPACITY_SEQUENCE_END -->')
        handoff = ROOT/'AGENTS.md'
        content = handoff.read_text()
        start = content.find('<!-- B0_CAPACITY_SEQUENCE_START -->')
        if start >= 0:
            end = content.index('<!-- B0_CAPACITY_SEQUENCE_END -->',start)+len('<!-- B0_CAPACITY_SEQUENCE_END -->')
            content = content[:start]+block+content[end:]
        else:
            content = content.replace('# AGENTS.md\n','# AGENTS.md\n\n'+block+'\n',1)
        handoff.write_text(content)
        with (ROOT/'docs/devlog/2026-10-28-phase2-b0-completion.md').open('a') as log:
            log.write(f"\n## {data['generated_at']} TX2托管测量收尾\n\nCodex测量程序记录状态{status}，收集{points}/6点；只写聚合数字，不含密钥、真实对话或人工标签。清理自有公网入口已执行，仍须接手核对；完整报告和阶段2未放行。Wiki按用户要求待同步。\n")
    print(json.dumps({'measured_sections':list(measured),'phase2_accepted':False,'full_aggregate_ready':False}))


if __name__ == '__main__':
    main()
