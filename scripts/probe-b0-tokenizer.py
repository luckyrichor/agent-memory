"""Check the official target-model tokenizer, preserving actual private I/O."""
import json,os,time
from pathlib import Path
import httpx

root=Path('.local/phase2/b0/tokenizer-probe-v1');root.mkdir(parents=True,exist_ok=False,mode=0o700)
body={'model':'doubao-seed-2-1-pro-260915','text':['完全虚构的分词计数对照。','Synthetic tokenizer calibration sample.']}
(root/'request-private.json').write_text(json.dumps(body,ensure_ascii=False))
start=time.monotonic()
r=httpx.post('https://ark.cn-beijing.volces.com/api/v3/tokenization',json=body,headers={'Authorization':'Bearer '+os.environ['ARK_API_KEY']},timeout=30,trust_env=False)
(root/'response-private.json').write_text(r.text)
data=r.json();result={'http':r.status_code,'model':data.get('model'),'seconds':time.monotonic()-start,'input_texts':len(body['text']),'source_documentation':'https://docs.volcengine.com/docs/ark/tokenization-api?lang=en','usage':data.get('usage'),'error_code':(data.get('error') or {}).get('code'),'counts':[x.get('total_tokens') for x in data.get('data',[])] if isinstance(data.get('data'),list) else None}
(root/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
for p in root.iterdir():p.chmod(0o600)
print(json.dumps(result))
