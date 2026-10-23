"""Run the authorized measurement under the user's service manager, without agent subprocess lifetime coupling."""
import argparse,json,os,subprocess,shutil
from pathlib import Path


def main():
 p=argparse.ArgumentParser();p.add_argument('--config',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--unit',required=True);a=p.parse_args()
 repo=Path(__file__).resolve().parents[1];output=a.output.resolve()
 if not output.is_relative_to(repo/'.local/phase2/b0') or output.exists():raise ValueError('new private run directory required')
 if not a.unit.startswith('agent-memory-b0-') or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789-' for c in a.unit):raise ValueError('scoped unit name required')
 log=output.with_suffix('.log');fd=os.open(log,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);os.close(fd)
 command=['systemd-run','--user','--collect','--unit='+a.unit,'--working-directory='+str(repo),'--property=UMask=0077','--property=KillSignal=SIGINT','--property=TimeoutStopSec=30','--property=StandardOutput=append:'+str(log),'--property=StandardError=append:'+str(log),'--setenv=PYTHONUNBUFFERED=1','--setenv=LARK_CLI_PATH='+str(shutil.which('lark-cli'))]
 for name in ('LARK_CHANNEL','LARK_CHANNEL_HOME','LARK_CHANNEL_PROFILE','LARK_CHANNEL_CONFIG','LARKSUITE_CLI_CONFIG_DIR','PATH','DOCKER_HOST','DOCKER_TLS_VERIFY','DOCKER_CERT_PATH'):
  if name in os.environ:command.append('--setenv='+name+'='+os.environ[name])
 python=str(repo/'.venv/bin/python');wrapper=str(repo/'scripts/with-llm-account.py')
 command.extend([python,wrapper,'ark-secondary',python,wrapper,'tokenhub-secondary',python,str(repo/'scripts/managed-b0-execution.py'),'--dataset','longmemeval_oracle,locomo,perltqa_zh,chinese_queries_v2,dulemon_gold,ecd_negative,longmemeval_s','--mode','both','--config',str(a.config.resolve()),'--metrics','EX,LC,RT,CX,E,RL,SC','--output',str(output)])
 subprocess.run(command,check=True)
 state=subprocess.check_output(['systemctl','--user','show',a.unit+'.service','--property=ActiveState','--value'],text=True).strip()
 print(json.dumps({'unit':a.unit+'.service','state':state,'log':str(log),'run':str(output),'credentials_in_command':False,'automatic_restart':False}))

if __name__=='__main__':main()
