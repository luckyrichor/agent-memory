"""Execute a finite B0 measurement, then deliver aggregate status to its authorized group."""
import hashlib,json,os,subprocess,sys
from pathlib import Path


def main():
 repo=Path(__file__).resolve().parents[1];arguments=sys.argv[1:];output=Path(arguments[arguments.index('--output')+1]);python=sys.executable
 config_path=Path(arguments[arguments.index('--config')+1]);config=json.loads(config_path.read_text());history=[];rotation=None;iteration=0
 if config.get('four_key_authorization')=='om_x100b6280467a68a4c3cc0005fe78816':
  from b0_autorotate import Rotation,save
  rotation=Rotation(output.parent/(output.name+'-rotation'),config)
 while True:
  result=subprocess.run([python,str(repo/'scripts/run-b0.py'),*arguments],cwd=repo,check=False)
  status_path=output/'status.json';status=json.loads(status_path.read_text()) if status_path.exists() else {'status':'interrupted_without_closed_status'}
  history.append(output)
  updated=rotation.next(config,output,history,status) if rotation else None
  if updated is None:break
  iteration+=1;config_path=rotation.root/f'continuation-{iteration:03d}-profile.json';save(config_path,updated)
  output=rotation.root/f'attempt-{iteration:03d}';arguments[arguments.index('--config')+1]=str(config_path);arguments[arguments.index('--output')+1]=str(output);config=updated
  current=repo/'docs/evals/b0-current.json';state=json.loads(current.read_text());state.update(status='automatically continuing after quota with a qualified key/model',active_run=str(output.relative_to(repo)),sample_config=str(config_path.relative_to(repo)),runtime_extraction_model=config.get('extraction_model'),runtime_extraction_provider=config.get('extraction_provider'),answer_model=config.get('answer_models',['doubao-seed-2-1-pro-260915'])[0],judge_model=config.get('judge_model','glm-5.2'),judge_provider=config.get('judge_provider','TokenHub'),embedding_model=config.get('embedding_model','doubao-embedding-vision-251215'),embedding_provider=config.get('embedding_provider','Ark'),active_role_accounts=config.get('role_accounts',{}),managed_process_completed=False,four_key_rotation_root=str(rotation.root.relative_to(repo)));save(current,state)
  print(json.dumps({'stage':'automatic-four-key-continuation','attempt':iteration,'run':str(output),'profile_changed_requires_new_comparison':not bool(config.get('resume_roots'))}),flush=True)
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
 current=repo/'docs/evals/b0-current.json';state=json.loads(current.read_text());state.pop('managed_active_state',None);state.update(status=status['status'],active_run=str(output.relative_to(repo)),calibration_exported=calibration.exists(),phase2_accepted=False,phase3_started=False,aggregate_report=str(delivery.relative_to(repo)),managed_process_completed=True);current.write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n')
 cli=os.environ['LARK_CLI_PATH'];relative=str(delivery.relative_to(repo))
 sent=subprocess.run([cli,'im','+messages-send','--as','bot','--chat-id','oc_e7156f4a7fa19da571d73b10169cd92f','--file',relative,'--idempotency-key','b0-'+hashlib.sha256(str(output).encode()).hexdigest()[:24]+'-closed'],cwd=repo,capture_output=True,text=True,check=False)
 try:sent_ok=sent.returncode==0 and json.loads(sent.stdout).get('ok') is True
 except (ValueError,TypeError):sent_ok=False
 (output/'delivery-result-private.json').write_text(json.dumps({'exit_code':sent.returncode,'stdout':sent.stdout,'stderr':sent.stderr},ensure_ascii=False,indent=2)+'\n');(output/'delivery-result-private.json').chmod(0o600)
 print(json.dumps({'stage':'managed-run-completed','status':status['status'],'aggregate_sent':sent_ok,'calibration_exists':calibration.exists(),'phase2_accepted':False}),flush=True)
 if result.returncode or status['status'] not in ('paused_for_owner_calibration','incomplete_calibration_population'):raise SystemExit(2)

if __name__=='__main__':main()
