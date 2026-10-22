"""One fictional packet to test provider support for the unchanged strict JSON schema."""
import json,os
from pathlib import Path
from datetime import datetime,timezone
import httpx
from agent_memory.evals.annotate import shared_sources
from agent_memory.evals.evidence_v3 import sha
from agent_memory.evals.model_policy import require_disabled_thinking
from agent_memory.evals.temporal import TemporalEvidenceBatch
from agent_memory.evals.temporal_output import validate_response
from agent_memory.evals.temporal_preflight import virtual_item
p=Path('.local/phase1/round3/temporal-v1/json-schema-probe-v1');p.mkdir(exist_ok=False,mode=0o700)
prompt=Path('docs/evals/prompts/labeling-guide-v3-temporal-v1.txt');rows=[virtual_item(i) for i in range(8)]
aliases={f'i{i}':r for i,r in enumerate(rows)}
body={'model':'hunyuan-turbos-vision-video-20250728','temperature':0,'thinking':{'type':'disabled'},'max_tokens':8192,
 'response_format':{'type':'json_schema','json_schema':{'name':'temporal_evidence_batch','strict':True,'schema':TemporalEvidenceBatch.model_json_schema()}},
 'messages':[{'role':'system','content':prompt.read_text()},{'role':'user','content':json.dumps(shared_sources([{**r,'item_id':key} for key,r in aliases.items()]),ensure_ascii=False)}]}
(p/'request.json').write_text(json.dumps(body,ensure_ascii=False)+'\n')
report={'at':datetime.now(timezone.utc).isoformat(),'model':body['model'],'fictional_only':True,'quality_evidence':False,'prompt_sha256':sha(prompt),'schema_unmodified':True,'calls':1}
try:
 response=httpx.post(os.environ['TENCENT_BASE_URL'].rstrip('/')+'/chat/completions',json=body,headers={'Authorization':'Bearer '+os.environ['TENCENT_API_KEY']},timeout=150,trust_env=False)
 (p/'response-private.json').write_text(response.text);report['http']=response.status_code
 if response.is_success:
  data=response.json();report['usage']=data.get('usage');require_disabled_thinking(data)
  checked=validate_response(data['choices'][0]['message']['content'],aliases)
  report.update(schema_valid=sum(r['schema_valid'] for r in checked),citation_valid=sum(r['citation_valid'] for r in checked),items=len(checked),observed_disabled_thinking=True)
 else:report['error_code']=(response.json().get('error') or {}).get('code')
except Exception as exc:report['error_type']=type(exc).__name__
(p/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps(report,ensure_ascii=False))
