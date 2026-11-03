"""Append aggregate-only local handoff for the current frozen run; never publish to Wiki."""
import argparse,hashlib,json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

START='<!-- B0_RUN_STATE_START -->'
END='<!-- B0_RUN_STATE_END -->'

def main():
 p=argparse.ArgumentParser();p.add_argument('--report',type=Path,required=True);p.add_argument('--repo',type=Path,default=Path.cwd());a=p.parse_args();repo=a.repo.resolve();report=json.loads(a.report.read_text());state=json.loads((repo/'docs/evals/b0-current.json').read_text());manifest=report['run_manifest'];identity=manifest['config'].get('baseline_configuration_id');run=a.report.resolve().parent.parent
 if not identity or identity!=state.get('baseline_configuration_id') or (repo/state['active_run']).resolve()!=run:return
 status=report['execution_status']['status'];row_count=sum(r['rows'] for r in report['measurements'].values())+sum(r['rows'] for r in report.get('flow_only',{}).values());calibration=report.get('calibration_rows',0);now=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat();relative=str(a.report.resolve().relative_to(repo));commit=manifest['harness_commit'][:7];dirty='，含未提交修改' if manifest.get('harness_uncommitted_changes') else ''
 content=f'''{START}
- 最新收尾核对时间：{now}；执行助手Codex；来源agent-memory@{commit}{dirty}。
- 当前配置：{identity}；实际结束状态：{status}；阶段2未验收，不进入阶段3。
- 已聚合实验行：{row_count}；新人工校准表行数：{calibration}。数量均取自本轮聚合，不把旧探索结果计入。
- 汇总证据：`{relative}`；当前状态索引：`docs/evals/b0-current.json`。计算已到结束/暂停节点，实际进程收尾须再查当前unit。
- 下一步：若状态为paused_for_owner_calibration，交负责人填写服务器私有校准表；不得代填；其他状态先按failure/usage查明原因，维持冻结模型与腾讯向量，不调用方舟。
- 飞书待同步：{now[:10]} 本轮聚合收尾与遗留；用户明确暂不写飞书，未擅自外发Wiki。
{END}'''
 agents=repo/'AGENTS.md';text=agents.read_text()
 if START in text and END in text:
  begin=text.index(START);end=text.index(END,begin)+len(END);text=text[:begin]+content+text[end:]
 else:text=text.replace('# AGENTS.md\n','# AGENTS.md\n\n'+content+'\n',1)
 agents.write_text(text)
 marker='<!-- frozen-b0-closeout:'+hashlib.sha256(str(run).encode()).hexdigest()[:20]+' -->'
 entry=f'\n\n{marker}\n## {now} 新配置B0运行收尾\n\n由Codex记录，agent-memory@{commit}{dirty}。状态{status}，聚合实验行{row_count}，新校准表{calibration}行。证据`{relative}`。阶段2未验收，PF、负责人校准和缺失观察适配器仍需后续完成，不进阶段3。原始答案/对话不写入此记录；飞书同步按用户要求暂缓。\n'
 for name in ('docs/progress.md','docs/devlog/2026-10-26-phase2-b0-frozen-deepseek-rebuild.md'):
  path=repo/name;path.parent.mkdir(parents=True,exist_ok=True);old=path.read_text() if path.exists() else ''
  if marker not in old:path.write_text(old+entry)
 print(json.dumps({'local_handoff_updated':True,'status':status,'calibration_rows':calibration,'wiki_written':False}))

if __name__=='__main__':main()
