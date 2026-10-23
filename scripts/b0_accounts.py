"""Private credential lookup; callers may record aliases, never returned credential values."""
from pathlib import Path

ACCOUNTS={'ark-primary':('Ark','volcengine.env','ARK_API_KEY'),'ark-secondary':('Ark','volcengine.env','ARK_API_KEY_2'),'tokenhub-primary':('TokenHub','tencent.env','TENCENT_API_KEY'),'tokenhub-secondary':('TokenHub','tencent.env','TENCENT_API_KEY_2')}

def credential(account):
 if account not in ACCOUNTS:raise ValueError('unknown account alias')
 provider,filename,key=ACCOUNTS[account];values={}
 for line in (Path('/home/ubuntu/.config/llm')/filename).read_text().splitlines():
  name,sep,value=line.partition('=')
  if sep and not name.lstrip().startswith('#'):values[name.strip()]=value.strip()
 token=values.get(key)
 if not token:raise ValueError('selected credential unavailable')
 base='https://ark.cn-beijing.volces.com/api/v3' if provider=='Ark' else values['TENCENT_BASE_URL'].rstrip('/')
 return provider,base,token
