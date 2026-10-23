"""Execute a finite B0 measurement, then deliver aggregate status to its authorized group."""
import hashlib,json,os,subprocess,sys
from pathlib import Path


def main():
 repo=Path(__file__).resolve().parents[1];arguments=sys.argv[1:];output=Path(arguments[arguments.index('--output')+1]);python=sys.executable
 result=subprocess.run([python,str(repo/'scripts/run-b0.py'),*arguments],cwd=repo,check=False)
 status_path=output/'status.json';status=json.loads(status_path.read_text()) if status_path.exists() else {'status':'interrupted_without_closed_status'}
 aggregate=output/'aggregate';summary=subprocess.run([python,str(repo/'scripts/summarize-b0.py'),'--input',str(output),'--output',str(aggregate)],cwd=repo,check=False)
 delivery=aggregate/'delivery.md'
 if summary.returncode or not delivery.exists():
  aggregate.mkdir(parents=True,exist_ok=True);delivery.write_text('# agent-memory B0状态\n\n状态：'+status['status']+'。阶段2未完成，聚合报告生成失败；原始记录仍在服务器私有目录，未作为正式分数发布。\n')
 calibration=output/'calibration-300-private.csv';message='\n## 托管任务结束状态\n\n'+status['status']+'。阶段2未验收；不进入阶段3。\n'
 if calibration.exists():
  import csv
  with calibration.open(encoding='utf-8-sig',newline='') as stream:count=sum(1 for _ in csv.DictReader(stream))
  message+=f'人工校准表已仅保存服务器：{calibration}；行数 {count}；SHA256 {hashlib.sha256(calibration.read_bytes()).hexdigest()}。人工栏空白，未显示系统组或裁判结果。请负责人在私有表中判定；计算已按约定暂停，不自行填写人工结论。\n'
 else:message+='尚未生成完整300条校准表，不要求负责人核对不存在的表。\n'
 message+='独立压测机仍待负责人准备，公网PF未运行。\n'
 with delivery.open('a') as stream:stream.write(message)
 current=repo/'docs/evals/b0-current.json';state=json.loads(current.read_text());state.update(status=status['status'],active_run=str(output.relative_to(repo)),calibration_exported=calibration.exists(),phase2_accepted=False,phase3_started=False,aggregate_report=str(delivery.relative_to(repo)),managed_process_completed=True);current.write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n')
 cli=os.environ['LARK_CLI_PATH'];relative=str(delivery.relative_to(repo))
 sent=subprocess.run([cli,'im','+messages-send','--as','bot','--chat-id','oc_e7156f4a7fa19da571d73b10169cd92f','--file',relative,'--idempotency-key','b0-'+output.name+'-closed'],cwd=repo,capture_output=True,text=True,check=False)
 (output/'delivery-result-private.json').write_text(json.dumps({'exit_code':sent.returncode,'stdout':sent.stdout,'stderr':sent.stderr},ensure_ascii=False,indent=2)+'\n');(output/'delivery-result-private.json').chmod(0o600)
 print(json.dumps({'stage':'managed-run-completed','status':status['status'],'aggregate_sent':sent.returncode==0,'calibration_exists':calibration.exists(),'phase2_accepted':False}),flush=True)
 if result.returncode or status['status'] not in ('paused_for_owner_calibration','incomplete_calibration_population'):raise SystemExit(2)

if __name__=='__main__':main()
