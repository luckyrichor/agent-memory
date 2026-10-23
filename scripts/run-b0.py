"""Single B0 entry: frozen runtime, dev-only inputs, private raw traces, no optimization."""
import argparse,asyncio,hashlib,json,os,random,subprocess,sys,time,threading,socket,math
from pathlib import Path
from datetime import datetime,timezone,timedelta
from uuid import uuid4,UUID

REPO=Path(__file__).resolve().parents[1]
SOURCE=REPO/'.local/phase2/b0/source-B0'
if '--config' in sys.argv:
 early=json.loads(Path(sys.argv[sys.argv.index('--config')+1]).read_text())
 if early.get('offline_fixture'):SOURCE=REPO
# Application package always resolves from B0; only eval helpers come from the current harness.
sys.path.insert(0,str(SOURCE/'src'))
import agent_memory.evals
agent_memory.evals.__path__.append(str(REPO/'src/agent_memory/evals'))
import httpx,jwt,uvicorn
from fastapi import FastAPI,Request
from starlette.responses import Response
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import create_engine,text,select
from sqlalchemy.engine import make_url
from testcontainers.community.postgres import PostgresContainer
from alembic import command
from alembic.config import Config
from agent_memory.api.app import create_app
from agent_memory.api.schemas import SearchRequest,ContextRequest
from agent_memory.api.event_schemas import EventRequest,EventBatchRequest,ConversationPayloadRequest,ToolResultPayloadRequest
from agent_memory.config import Settings
from agent_memory.sdk import MemoryClient,MemoryAPIError
from agent_memory.domain.enums import ScopeKind,MemoryType
from agent_memory.domain.models import MemoryScope
from agent_memory.domain.principal import RequestPrincipal
from agent_memory.application.extraction_worker import ExtractionWorker
from agent_memory.application.outbox_dispatcher import OutboxDispatcher
from agent_memory.infrastructure.llm_extractor import build_extractor
from agent_memory.application.embedding import EmbeddingWorker
from agent_memory.infrastructure.embedding import HTTPEmbeddingProvider,PostgresEmbeddingBackend
from agent_memory.evals.api_import import source_time
from agent_memory.infrastructure.db import create_session_factory,session_for_principal
from agent_memory.infrastructure.event_repositories import PostgresExtractionBackend,PostgresOutboxRepository
from agent_memory.evals.datasets import file_hash
from agent_memory.evals.b0 import cosine_rank,calibration_sample,chunk_source_documents,measurement_signature,complete_checkpoint,compatible_measurement,compatible_result_model
from agent_memory.evals.b0_rotation import vendor
from agent_memory.evals.metrics import ratio,evidence_retrieval,latency


def write(path,data):
 path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
 path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n');path.chmod(0o600)
def append(path,data):
 with path.open('a') as f:f.write(json.dumps(data,ensure_ascii=False)+'\n')
 path.chmod(0o600)
def rows(path):
 with Path(path).open() as f:return [json.loads(s) for s in f if s.strip()]
def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


class ModelIO:
 def __init__(self,out,cache_roots=(),fixture=False,config=None):
  self.config=config or {};self.embedding_model=self.config.get('embedding_model','doubao-embedding-vision-251215');self.embedding_provider=self.config.get('embedding_provider','Ark');self.embedding_protocol=self.config.get('embedding_protocol','ark')
  self.fixture=fixture;self.credentials={}
  self.vector_cache={}
  for root in cache_roots:
   root=Path(root)
   if not (root/"usage.jsonl").exists():continue
   for record in rows(root/"usage.jsonl"):
    if record.get("role")!="embedding" or record.get("provider")!=self.embedding_provider or record.get("http")!=200 or record.get("cache_hit") or record.get("fixture_only") or record.get("new_http_call") is False:continue
    request=root/f"calls/{record['call_id']:07d}-request-private.json";response=root/f"calls/{record['call_id']:07d}-response-{record['attempt']}-private.json"
    if not request.exists() or not response.exists():continue
    body=json.loads(request.read_text());data=json.loads(response.read_text())
    if body.get("model")!=self.embedding_model or body.get("dimensions")!=1024:continue
    if data.get("model")!=self.embedding_model:continue
    vector=(data.get("data",{}).get("embedding",[]) if isinstance(data.get("data"),dict) else (data.get("data") or [{}])[0].get("embedding",[]))
    if len(vector)!=1024:continue
    if not all(isinstance(x,(int,float)) and math.isfinite(x) for x in vector) or not any(vector):continue
    self.vector_cache.setdefault(digest(body),(response,file_hash(response)))
  self.out=out;self.clients={};self.semaphores={};self.counter_lock=threading.Lock();self.index=0;self.calls=[];self.runtime_blocked=False;self.exhausted=set()
 async def request(self,role,body,*,provider='Ark'):
  if self.runtime_blocked:raise RuntimeError('RUNTIME_QUOTA_PAUSED')
  loop=id(asyncio.get_running_loop())
  if loop not in self.clients:self.clients[loop]=httpx.AsyncClient(timeout=90,trust_env=False)
  if loop not in self.semaphores:self.semaphores[loop]=asyncio.Semaphore(4)
  async with self.semaphores[loop]:
   if self.runtime_blocked:raise RuntimeError('RUNTIME_QUOTA_PAUSED')
   if (role,provider,body['model']) in self.exhausted:raise RuntimeError('EVALUATION_MODEL_QUOTA')
   with self.counter_lock:self.index+=1;index=self.index
   request_path=self.out/f'calls/{index:07d}-request-private.json';write(request_path,body)
   endpoint='tokenization' if role=='tokenizer' else (('embeddings/multimodal' if self.embedding_protocol=='ark' else 'embeddings') if role=='embedding' else 'chat/completions')
   base='https://ark.cn-beijing.volces.com/api/v3' if provider=='Ark' else os.environ.get('TENCENT_BASE_URL','https://tokenhub.tencentmaas.com/v1').rstrip('/')
   if self.fixture:
    if role=='embedding':data={'model':'offline-fixture-not-a-real-model','data':{'embedding':[1.0]+[0.0]*1023} if self.embedding_protocol=='ark' else [{'index':0,'embedding':[1.0]+[0.0]*1023}]}
    elif role=='tokenizer':data={'model':'offline-fixture-not-a-real-model','data':[{'total_tokens':len(body['text'][0])}]}
    else:
     content=json.dumps({'memories':[{'content':'Synthetic fixture memory.'}]}) if role=='extraction' else (json.dumps({'correct':True,'reason_code':'MATCH'}) if role in ('judge','cross-reference') else 'fixture answer')
     data={'model':'offline-fixture-not-a-real-model','choices':[{'message':{'content':content}}]}
    write(self.out/f'calls/{index:07d}-response-fixture-private.json',data)
    record={'call_id':index,'attempt':0,'at':datetime.now(timezone.utc).isoformat(),'role':role,'provider':'offline-fixture','model':body['model'],'response_model':data.get('model'),'http':200,'usage':None,'seconds':0,'input_bytes':0,'cache_hit':False,'new_http_call':False,'fixture_only':True}
    self.calls.append(record);append(self.out/'usage.jsonl',record);return data
   if role=='embedding' and digest(body) in self.vector_cache:
    origin,expected=self.vector_cache[digest(body)];assert file_hash(origin)==expected
    data=json.loads(origin.read_text());write(self.out/f'calls/{index:07d}-response-cached-private.json',data)
    record={'call_id':index,'attempt':0,'at':datetime.now(timezone.utc).isoformat(),'role':role,'provider':provider,'model':body['model'],'response_model':data.get('model'),'http':200,'usage':None,'historical_usage_not_new_tokens':data.get('usage'),'seconds':0,'input_bytes':0,'request_sha256':digest(body),'cache_hit':True,'new_http_call':False,'source_response_path':str(origin),'source_response_sha256':expected}
    self.calls.append(record);append(self.out/'usage.jsonl',record);return data
   from b0_accounts import credential
   choices=self.config.get('role_accounts',{}).get(role,{})
   account=choices.get(provider,os.environ.get('AGENT_MEMORY_ARK_ACCOUNT' if provider=='Ark' else 'AGENT_MEMORY_TOKENHUB_ACCOUNT','ark-secondary' if provider=='Ark' else 'tokenhub-secondary'))
   if account not in self.credentials:self.credentials[account]=credential(account)
   actual_provider,base,token=self.credentials[account]
   if actual_provider!=provider:raise ValueError('ACCOUNT_PROVIDER_MISMATCH')
   start=time.monotonic();response=None
   for attempt in range(3):
    try:
     response=await self.clients[loop].post(base+'/'+endpoint,json=body,headers={'Authorization':'Bearer '+token})
     data=response.json()
    except (httpx.HTTPError,ValueError) as error:
     data={'error':{'code':type(error).__name__}};response=None
    status=response.status_code if response is not None else None
    write(self.out/f'calls/{index:07d}-response-{attempt}-private.json',data)
    usage=data.get('usage');code=(data.get('error') or {}).get('code')
    record={'call_id':index,'attempt':attempt,'at':datetime.now(timezone.utc).isoformat(),'role':role,'provider':provider,'model':body['model'],'response_model':data.get('model'),'http':status,'error_code':code,'usage':usage,'seconds':time.monotonic()-start,'input_bytes':len(json.dumps(body,ensure_ascii=False).encode()),'request_sha256':digest(body),'cache_hit':False,'account':account}
    self.calls.append(record);append(self.out/'usage.jsonl',record)
    quota=status==402 or code in ('SetLimitExceeded','401010','QuotaExceeded','InsufficientBalance')
    if quota and role in ('extraction','embedding'):
     self.runtime_blocked=True;write(self.out/'runtime-quota-pause.json',record)
     raise RuntimeError('RUNTIME_QUOTA_PAUSED')
    if status==200:return data
    if quota:
     self.exhausted.add((role,provider,body['model']))
     raise RuntimeError('EVALUATION_MODEL_QUOTA')
    if status not in (None,429,500,502,503,504):break
    await asyncio.sleep(2**attempt)
   return {'error':data.get('error',{'code':'INVALID_RESPONSE'})}
 async def embedding(self,content):
  body={'model':self.embedding_model,'input':[{'type':'text','text':content}] if self.embedding_protocol=='ark' else content,'dimensions':1024,'encoding_format':'float'}
  data=await self.request('embedding',body,provider=self.embedding_provider)
  if 'data' not in data:raise ValueError('INVALID_EMBEDDING_RESPONSE')
  vector=data['data']['embedding'] if isinstance(data['data'],dict) else data['data'][0]['embedding']
  if len(vector)!=1024 or not all(isinstance(x,(int,float)) and math.isfinite(x) for x in vector) or not any(vector):raise ValueError('INVALID_EMBEDDING_RESPONSE')
  return vector
 async def answer(self,question,context,model='doubao-seed-2-1-pro-260915',when=None,full_history=False):
  body={'model':model,'temperature':0,'thinking':{'type':'disabled'},'max_tokens':512,'messages':[{'role':'system','content':(REPO/'docs/evals/prompts/b0-answer-v1.txt').read_text()},{'role':'user','content':json.dumps({'context':context,'question':question,'question_date':when},ensure_ascii=False)}]}
  original_chars=len(json.dumps(context,ensure_ascii=False));truncated=False
  for _ in range(24):
   data=await self.request('answer',body,provider=self.config.get('answer_provider','Ark' if model.startswith('doubao') else 'TokenHub'))
   error_text=str((data.get('error') or {}).get('message','')).lower()
   context_error=any(t in error_text for t in ('context length','maximum context','context window','input token','input length','prompt is too long'))
   if 'choices' in data or not (full_history and context_error):break
   # Deterministic oldest-first truncation on explicit provider context rejection only.
   if isinstance(context,list) and len(context)>1:context=context[max(1,len(context)//2):]
   else:
    content=json.dumps(context,ensure_ascii=False) if not isinstance(context,str) else context
    if len(content)<2:break
    context=content[len(content)//2:]
   truncated=True
   body['messages'][1]['content']=json.dumps({'context':context,'question':question,'question_date':when},ensure_ascii=False)
  data['_b0_full_context_truncation']={'truncated':truncated,'original_serialized_chars':original_chars,'retained_serialized_chars':len(json.dumps(context,ensure_ascii=False)),'basis':'serialized Unicode characters, not model token ratio; drop oldest only on explicit context-length rejection'}
  if 'choices' not in data:return None,data
  return data['choices'][0]['message']['content'],data
 async def grade(self,row,model='glm-5.2',*,role='judge'):
  prompt=(REPO/'docs/evals/prompts/judge-v1.txt').read_text()
  if row['dataset'].startswith('longmemeval'):
   rubrics=json.loads((REPO/'docs/evals/prompts/b0-lme-judge-rubrics-v1.json').read_text())['templates']
   template=rubrics[row['category']]
   prompt+='\nUse this task-specific rubric, serialize the decision as JSON correct/reason_code, not yes/no. Placeholder values are supplied as untrusted user JSON:\n'+template
   content=json.dumps({k:row[k] for k in ('question','reference','answer')},ensure_ascii=False)
  else:content=json.dumps({k:row[k] for k in ('question','reference','answer')},ensure_ascii=False)
  body={'model':model,'temperature':0,'thinking':{'type':'disabled'},'max_tokens':256,'response_format':{'type':'json_object'},'messages':[{'role':'system','content':prompt},{'role':'user','content':content}]}
  data=await self.request(role,body,provider=self.config.get('judge_provider','TokenHub') if role=='judge' else self.config.get('cross_reference_provider','TokenHub'))
  try:
   value=json.loads(data['choices'][0]['message']['content'])
   assert set(value)=={'correct','reason_code'} and type(value['correct']) is bool and value['reason_code'] in ('MATCH','MISMATCH')
   return value['correct']
  except (KeyError,ValueError,TypeError,AssertionError):return None


async def measure(args,appurl):
 out=args.output;config=json.loads(args.config.read_text());io=ModelIO(out,config.get('embedding_cache_roots',[]),config.get('offline_fixture',False),config=config)
 manifest=json.loads((Path(config['datasets_manifest']) if config.get('offline_fixture') else REPO/'docs/baselines/b0/datasets-v1.json').read_text());names=[] if args.dataset=='correctness' else (list(manifest) if args.dataset=='all' else args.dataset.split(','))
 config=json.loads(args.config.read_text());seed=config['seed'];all_results=[];imports=[];status='interrupted'
 with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
 proxy=FastAPI()
 @proxy.post('/{role}')
 async def forward(role:str,request:Request):
  body=await request.json()
  # Sampling configuration only; no changes to frozen extraction text/schema.
  if role=='extraction':body['temperature']=0
  provider=config.get('extraction_provider','Ark') if role=='extraction' else config.get('embedding_provider','Ark')
  try:data=await io.request(role,body,provider=provider)
  except RuntimeError:return Response('{}',status_code=402)
  return Response(json.dumps(data),media_type='application/json')
 server=uvicorn.Server(uvicorn.Config(proxy,host='127.0.0.1',port=port,log_level='error',access_log=False))
 thread=threading.Thread(target=server.run,daemon=True);thread.start()
 while not server.started:await asyncio.sleep(.05)
 key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
 public=key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo).decode()
 settings=Settings(database_url=appurl,jwt_public_key=public,jwt_issuer='b0-eval',jwt_audience='b0-eval',embedding_model=config.get('embedding_model','doubao-embedding-vision-251215'),embedding_protocol=config.get('embedding_protocol','ark'),embedding_endpoint=f'http://127.0.0.1:{port}/embedding',embedding_token='private-local-forwarder',embedding_trust_env=False,extraction_model=config.get('extraction_model','doubao-seed-2-1-pro-260915'),extraction_endpoint=f'http://127.0.0.1:{port}/extraction',extraction_token='private-local-forwarder',log_level='ERROR',trace_exporter='none',metrics_exporter='none')
 app=create_app(settings);sessions=create_session_factory(app.state.engine)
 from b0_correctness import measure_correctness
 await measure_correctness(app,sessions,key,out,runtime_label='offline fixture on current source' if config.get('offline_fixture') else 'B0')
 async def run_conversation(dataset,conv,mode,repeat):
  tenant,user=uuid4(),uuid4();workspace='b0';scope=MemoryScope(ScopeKind.WORKSPACE,workspace,None)
  token=jwt.encode({'iss':'b0-eval','aud':'b0-eval','sub':str(user),'tenant_id':str(tenant),'roles':['developer'],'permissions':['memory:read','memory:write'],'allowed_workspace_ids':[workspace],'exp':datetime.now(timezone.utc)+timedelta(hours=12)},key,algorithm='RS256')
  mapping=[];rejected=[];chunks=[];naive_source=chunk_source_documents(conv['documents'])
  cid=conv['conversation_id'];at=datetime.now(timezone.utc)
  async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://b0-eval') as api:
   sdk=MemoryClient(api,token=token)
   for doc in conv['documents']:
    for start in range(0,len(doc['text']),4000):
     content=doc['text'][start:start+4000];chunk={**doc,'text':content,'part':start//4000}
     stable='b0:'+digest([cid,doc['source_id'],start,mode,repeat])
     try:
      if mode=='direct':
       value=await sdk.remember(content,MemoryType.EPISODIC,scope,idempotency_key=stable)
       chunk.update(version_id=str(value.version_id),memory_id=str(value.memory_id));mapping.append(chunk)
      else:
       role=doc['role'];payload=ConversationPayloadRequest(role=role,summary=content) if role in ('user','assistant') else ToolResultPayloadRequest(tool_name='public-benchmark-source-record',exit_code=0,summary=content)
       occurred=at
       if doc.get('occurred_at'):
        try:occurred=source_time(doc['occurred_at'])
        except ValueError:pass
       event=EventRequest(idempotency_key=stable,session_id='b0:'+digest([cid,doc['session_id']]),sequence_number=len(chunks)+1,event_type='conversation.message' if role in ('user','assistant') else 'tool.result',agent_id='b0-eval',occurred_at=occurred,scope={'kind':'workspace','workspace_id':workspace},payload=payload)
       value=await sdk.ingest_events(EventBatchRequest(events=[event]));chunk['event_id']=str(value.items[0].event_id);mapping.append(chunk)
      chunks.append(chunk)
     except MemoryAPIError as error:
      if error.status_code!=422:raise
      rejected.append({'source_id':doc['source_id'],'part':start//4000,'status':error.status_code,'code':error.code})
   if mode=='full':
    principal=RequestPrincipal(tenant,UUID(int=0),frozenset({'outbox_dispatcher'}),frozenset({'queue:dispatch'}),frozenset())
    runtime=httpx.AsyncClient(timeout=15,trust_env=False);extractor=build_extractor(settings,runtime)
    async with session_for_principal(sessions,principal) as session:
     dispatcher=OutboxDispatcher(PostgresOutboxRepository(session,new_id=uuid4,now=lambda:datetime.now(timezone.utc)),extractor.version)
     while await dispatcher.dispatch_once(tenant,100):pass
    worker=ExtractionWorker(PostgresExtractionBackend(sessions,new_id=uuid4,now=lambda:datetime.now(timezone.utc),extractor_version=extractor.version),extractor,now=lambda:datetime.now(timezone.utc),lease_duration=timedelta(seconds=30))
    outcomes=[]
    while True:
     result=await worker.run_once(tenant,'b0-worker');outcomes.append({'outcome':result.outcome,'reason_code':result.reason_code,'extractor_last_reason':extractor.last_reason,'extractor_last_failure':extractor.last_failure})
     if io.runtime_blocked:raise RuntimeError('RUNTIME_QUOTA_PAUSED')
     if result.outcome=='no_job':
      async with session_for_principal(sessions,principal) as session:
       pending=await session.scalar(text("SELECT count(*) FROM jobs WHERE tenant_id=:tenant AND job_type='extract_event' AND status IN ('pending','running','retry_wait')"),{'tenant':tenant})
      if not pending:break
      if len(outcomes)>len(chunks)*6+30:raise RuntimeError('EXTRACTION_QUEUE_INCOMPLETE')
      await asyncio.sleep(2)
    await runtime.aclose()
    # Observation only: no promotion of CANDIDATE to ACTIVE, no runtime changes.
    async with session_for_principal(sessions,principal) as session:
     values=(await session.execute(text('SELECT v.memory_version_id,v.content,m.memory_id,m.status,e.event_id FROM memory_versions v JOIN memories m ON m.tenant_id=v.tenant_id AND m.current_version_id=v.memory_version_id JOIN evidence e ON e.tenant_id=v.tenant_id AND e.memory_version_id=v.memory_version_id WHERE v.tenant_id=:tenant'),{'tenant':tenant})).all()
    eventmap={r['event_id']:r for r in mapping};mapping=[{**eventmap[str(eid)],'version_id':str(vid),'memory_id':str(mid),'text':content,'memory_status':status} for vid,content,mid,status,eid in values]
   else:outcomes=[]
   # Run the actual frozen embedding worker. Do not bypass the public ingestion pipeline.
   embedding_http=httpx.AsyncClient(timeout=10,trust_env=False)
   embedding_backend=PostgresEmbeddingBackend(sessions)
   embedding_worker=EmbeddingWorker(embedding_backend,HTTPEmbeddingProvider(embedding_http,endpoint=settings.embedding_endpoint,model=settings.embedding_model,token=settings.embedding_token.get_secret_value(),protocol=settings.embedding_protocol))
   embedding_outcomes=[]
   principal=RequestPrincipal(tenant,UUID(int=0),frozenset({'embedding_worker'}),frozenset({'queue:work'}),frozenset())
   while True:
    result=await embedding_worker.run_once(tenant,'b0-embedding-worker')
    embedding_outcomes.append({'outcome':result.outcome,'reason_code':result.reason_code})
    if io.runtime_blocked:raise RuntimeError('RUNTIME_QUOTA_PAUSED')
    if result.outcome=='no_job':
     async with session_for_principal(sessions,principal) as session:
      pending=await session.scalar(text("SELECT count(*) FROM jobs WHERE tenant_id=:tenant AND job_type='embed_memory' AND status IN ('pending','running','retry_wait')"),{'tenant':tenant})
     if not pending:break
     await asyncio.sleep(2)
   await embedding_http.aclose()
   async with session_for_principal(sessions,principal) as session:
    loaded=(await session.execute(text('SELECT e.memory_version_id,e.embedding::text,v.content FROM memory_embeddings e JOIN memory_versions v ON v.memory_version_id=e.memory_version_id AND v.tenant_id=e.tenant_id WHERE e.tenant_id=:tenant AND e.model=:model'),{'tenant':tenant,'model':settings.embedding_model})).all()
   by_text={content:json.loads(vec) for _vid,vec,content in loaded}
   # Direct naive-vector receives EVERY original bounded source chunk, even those rejected
   # by the tested system's content policy. Full mode receives all extracted candidates,
   # without filtering their lifecycle, subject, type, workspace or other metadata.
   naive_mapping=naive_source if mode=='direct' else list(mapping)
   async def external_vector(item):
    return by_text[item['text']] if item['text'] in by_text else await io.embedding(item['text'])
   vectors=await asyncio.gather(*(external_vector(r) for r in naive_mapping))
   import_record={'extraction_model':config.get('extraction_model','doubao-seed-2-1-pro-260915') if mode=='full' else None,'embedding_model':io.embedding_model,'embedding_provider':io.embedding_provider,'dataset':dataset,'conversation_id':cid,'mode':mode,'repeat':repeat,'source_documents':len(conv['documents']),'chunks':len(chunks),'memories':len(mapping),'naive_corpus_count':len(naive_mapping),'naive_includes_system_rejected_source_chunks':mode=='direct','embedding_outcomes':embedding_outcomes,'rejected':rejected,'extraction_outcomes':outcomes,'source_role_unknown_as_tool_result':sum(d['role']=='source' for d in conv['documents']),'event_occurred_at_basis':'original source time when parseable, otherwise explicit import receipt time; source text/time retained in mapping','active_memories':sum(r.get('memory_status','active')=='active' for r in mapping)}
   imports.append(import_record);append(out/'imports-private.jsonl',import_record);write(out/f'mappings/{digest([dataset,cid,mode,repeat])}.json',mapping)
   questions=list(conv['questions']);rng=random.Random(seed);rng.shuffle(questions);questions=questions[:config['questions_per_conversation']]
   for q in questions:
    qvec=await io.embedding(q['text']);rank=cosine_rank(qvec,vectors,10) if vectors else []
    observed=await sdk.search(SearchRequest(query=q['text'],workspace_id=workspace,limit=10))
    packet=await sdk.context(ContextRequest(query=q['text'],workspace_id=workspace,limit=10,token_budget=config['system_context_budget']))
    by_version={r['version_id']:r for r in mapping};level=conv.get('metadata',{}).get('evidence_level')
    sourcekey='session_id' if level=='session' else 'source_id'
    groups={'no-memory':([],[]),'full-context':([{'text':d['text'],'role':d['role'],'occurred_at':d.get('occurred_at')} for d in conv['documents']],[]),'naive-vector':([naive_mapping[i]['text'] for i in rank],[[naive_mapping[i][sourcekey]] for i in rank]),'system':(packet.rendered,[[by_version[str(hit.version_id)][sourcekey]] if str(hit.version_id) in by_version else ['unmapped:'+str(hit.version_id)] for hit in observed.items])}
    for group,(context,evidence) in groups.items():
     answer,data=None,{}
     row={'pipeline_extraction_model':config.get('extraction_model','doubao-seed-2-1-pro-260915') if mode=='full' else None,'pipeline_embedding_model':io.embedding_model,'pipeline_embedding_provider':io.embedding_provider,'row_id':digest([dataset,cid,q['question_id'],mode,group,repeat]),'dataset':dataset,'conversation_id':cid,'question_id':q['question_id'],'category':q['category'],'mode':mode,'system':group,'repeat':repeat,'question':q['text'],'reference':q['answer'],'answer':answer,'answer_model':data.get('model'),'answer_usage':data.get('usage'),'answer_valid':answer is not None,'ranked_evidence_sets':evidence,'retrieval':{str(k):evidence_retrieval(evidence,q['relevant'],k) for k in (1,3,5,10)} if q['evidence_available'] and not q['abstention'] and group in ('system','naive-vector') else {},'system_vector_status':observed.vector_status if group=='system' else None,'RT6':float(not evidence) if q['abstention'] and group in ('system','naive-vector') else None,'flow_only':q['category'] in conv.get('metadata',{}).get('flow_only_categories',[]),'full_context_truncated':False,'full_context_input_bytes':len(json.dumps(context,ensure_ascii=False).encode()),'system_context':{'used_tokens':packet.used_tokens,'budget':packet.budget,'truncated':packet.truncated,'counter':packet.counter} if group=='system' else None,'judge_correct':None,'judge_model':'glm-5.2','formal_score':False}
     row.update(context=context,question_date=conv.get('metadata',{}).get('question_date'))
     all_results.append(row);append(out/'results-private.jsonl',row)
     print(json.dumps({'dataset':dataset,'mode':mode,'repeat':repeat,'group':group,'completed_rows':len(all_results),'model_calls':len(io.calls)}),flush=True)
 def resume_dataset(dataset,selected):
  modes=['direct','full'] if args.mode=='both' else [args.mode]
  expected=set()
  for conv in selected:
   questions=list(conv['questions']);random.Random(seed).shuffle(questions)
   for q in questions[:config['questions_per_conversation']]:
    for repeat in range(3):
     for mode in modes:
      for group in ('no-memory','full-context','naive-vector','system'):expected.add(digest([dataset,conv['conversation_id'],q['question_id'],mode,group,repeat]))
  for path in config.get('resume_roots',[]):
   root=Path(path);prior=json.loads((root/'run-manifest.json').read_text())
   if not compatible_measurement(prior['config'],config) or prior['mode']!=args.mode:raise ValueError('RESUME_MEASUREMENT_CONFIG_MISMATCH')
   current_prompts=json.loads((out/'run-manifest.json').read_text())['prompt_hashes']
   if prior['prompt_hashes']!=current_prompts:raise ValueError('RESUME_PROMPT_MISMATCH')
   selection=root/(dataset+'-selection-private.json')
   if not selection.exists():continue
   selection=json.loads(selection.read_text())
   if selection['source_sha256']!=manifest[dataset]['sha256'] or selection['ids']!=[c['conversation_id'] for c in selected]:raise ValueError('RESUME_DATA_MISMATCH')
   imported=[r for r in rows(root/'imports-private.jsonl') if r['dataset']==dataset]
   keys=[(r['conversation_id'],r['mode'],r['repeat']) for r in imported]
   expected_imports={(c['conversation_id'],mode,repeat) for c in selected for mode in modes for repeat in range(3)}
   if len(keys)!=len(set(keys)) or set(keys)!=expected_imports:continue
   tables=[root/f'table-{dataset}-{mode}-private.json' for mode in modes]
   if expected and not all(p.exists() for p in tables):continue
   saved=[r for p in tables if p.exists() for r in json.loads(p.read_text())]
   if not complete_checkpoint(saved,expected):continue
   if not config.get('offline_fixture') and any(not compatible_result_model(r.get('answer_model'),config.get('answer_models',['doubao-seed-2-1-pro-260915'])[0],config) or not compatible_result_model(r.get('judge_model'),config.get('judge_model','glm-5.2'),config) for r in saved):continue
   if bool(prior.get('offline_fixture_only'))!=bool(config.get('offline_fixture')) or prior['runtime_application_file']!=str(SOURCE/'src/agent_memory/api/app.py'):raise ValueError('RESUME_NOT_FROZEN_B0')
   all_results.extend(saved);imports.extend(imported)
   for r in saved:append(out/'results-private.jsonl',r)
   for r in imported:append(out/'imports-private.jsonl',r)
   for p in tables:
    if p.exists():write(out/p.name,json.loads(p.read_text()))
   append(out/'resumed-datasets.jsonl',{'dataset':dataset,'from_run':str(root),'actual_original_repeats':3,'new_answer_calls':0,'rows':len(saved),'table_hashes':{p.name:file_hash(p) for p in tables if p.exists()},'parent_run_manifest_sha256':file_hash(root/'run-manifest.json'),'parent_harness_commit':prior['harness_commit'],'measurement_signature':measurement_signature(config),'same_source_prompt_data_required':True,'family_continuation_authorization':config.get('family_continuation_authorization'),'actual_answer_models':sorted({r.get('answer_model') for r in saved if r.get('answer_model')}),'actual_judge_models':sorted({r.get('judge_model') for r in saved if r.get('judge_model')}),'database_state_restored':False,'scope':'complete evaluation rows and import observations only; previous DB is not restored; parent actual calls remain in their original ledger'})
   print(json.dumps({'stage':'resumed-complete-dataset','dataset':dataset,'rows':len(saved),'new_calls':0}),flush=True)
   return True
  return False
 def resume_conversation(dataset,conv,mode,repeat):
  # Only a complete immutable conversation/mode/repeat checkpoint is reusable.
  questions=list(conv['questions']);random.Random(seed).shuffle(questions)
  expected={digest([dataset,conv['conversation_id'],q['question_id'],mode,group,repeat]) for q in questions[:config['questions_per_conversation']] for group in ('no-memory','full-context','naive-vector','system')}
  current_manifest=json.loads((out/'run-manifest.json').read_text())
  for path in config.get('resume_roots',[]):
   root=Path(path);prior=json.loads((root/'run-manifest.json').read_text())
   if not compatible_measurement(prior['config'],config) or prior['mode']!=args.mode:raise ValueError('RESUME_MEASUREMENT_CONFIG_MISMATCH')
   if prior['prompt_hashes']!=current_manifest['prompt_hashes'] or prior['runtime_application_file']!=current_manifest['runtime_application_file'] or prior['baseline_commit']!=current_manifest['baseline_commit'] or bool(prior.get('offline_fixture_only'))!=bool(config.get('offline_fixture')):raise ValueError('RESUME_NOT_FROZEN_B0')
   selection=root/(dataset+'-selection-private.json')
   if not selection.exists():continue
   if json.loads(selection.read_text())!=json.loads((out/selection.name).read_text()):raise ValueError('RESUME_DATA_MISMATCH')
   imported=[r for r in rows(root/'imports-private.jsonl') if r['dataset']==dataset and r['conversation_id']==conv['conversation_id'] and r['mode']==mode and r['repeat']==repeat] if (root/'imports-private.jsonl').exists() else []
   raw=root/'results-private.jsonl'
   saved=[r for r in rows(raw) if r['row_id'] in expected] if raw.exists() else []
   if len(imported)!=1 or not complete_checkpoint(saved,expected):continue
   all_results.extend(saved);imports.extend(imported)
   for row in saved:append(out/'results-private.jsonl',row)
   append(out/'imports-private.jsonl',imported[0])
   append(out/'resumed-conversations.jsonl',{'dataset':dataset,'conversation_id':conv['conversation_id'],'mode':mode,'repeat':repeat,'from_run':str(root),'rows':len(saved),'new_model_calls':0,'database_state_restored':False,'parent_manifest_sha256':file_hash(root/'run-manifest.json'),'parent_results_sha256':file_hash(raw),'parent_imports_sha256':file_hash(root/'imports-private.jsonl'),'family_continuation_authorization':config.get('family_continuation_authorization')})
   return True
  return False
 def saved_stages(table):
  # Per-row successes survive quota failures; never adopt them across a family/space change.
  saved={};wanted={r['row_id'] for r in table};current=json.loads((out/'run-manifest.json').read_text())
  for path in reversed(config.get('resume_roots',[])):
   root=Path(path);prior=json.loads((root/'run-manifest.json').read_text())
   if not compatible_measurement(prior['config'],config) or prior['mode']!=args.mode or prior['prompt_hashes']!=current['prompt_hashes']:raise ValueError('RESUME_STAGE_CONFIG_MISMATCH')
   for name in ('answers-checkpoint-private.jsonl','grades-checkpoint-private.jsonl',*[p.name for p in sorted(root.glob('table-*-private.json'))]):
    source=root/name
    if not source.exists():continue
    for item in (json.loads(source.read_text()) if source.suffix=='.json' else rows(source)):
     if 'context_sha256' not in item:item['context_sha256']=digest(item['context'])
     if item['row_id'] not in wanted:continue
     saved.setdefault(item['row_id'],{}).update(item)
     saved[item['row_id']]['checkpoint_origin']={'path':str(source),'sha256':file_hash(source),'manifest_sha256':file_hash(root/'run-manifest.json')}
  for row in table:
   item=saved.get(row['row_id'])
   if not item or item.get('context_sha256')!=digest(row['context']) or any(item.get(field)!=row[field] for field in ('question','reference','category')):continue
   if not (config.get('offline_fixture') and item.get('answer_model')=='offline-fixture-not-a-real-model') and not compatible_result_model(item.get('answer_model'),config.get('answer_models',['doubao-seed-2-1-pro-260915'])[0],config):continue
   for field in ('answer','answer_valid','answer_model','answer_usage','full_context_truncation','full_context_truncated'):row[field]=item[field]
   row['_answer_checkpoint']=True
   if 'judge_correct' in item and compatible_result_model(item.get('judge_model'),config.get('judge_model','glm-5.2'),config):
    row.update(judge_correct=item['judge_correct'],judge_model=item['judge_model'],_grade_checkpoint=True)
   append(out/'resumed-stages-private.jsonl',{'row_id':row['row_id'],'answer_model':row['answer_model'],'judge_model':row.get('judge_model') if row.get('_grade_checkpoint') else None,'context_sha256':item['context_sha256'],'new_answer_calls':0,'origin':item['checkpoint_origin'],'family_continuation_authorization':config.get('family_continuation_authorization')})
 async def finish_tables(table_rows):
  saved_stages(table_rows)
  # Measure the frozen byte counter; never replace it with the target-model tokenizer.
  async def context_tokens(row):
   if row['system']!='system' or row.get('_answer_checkpoint'):return
   try:
    data=await io.request('tokenizer',{'model':config.get('answer_models',['doubao-seed-2-1-pro-260915'])[0],'text':[row['context']]})
    row['actual_rendered_context_tokens']=data['data'][0]['total_tokens'];row['context_tokenizer_model']=data.get('model')
   except (RuntimeError,KeyError,TypeError,IndexError):row['actual_rendered_context_tokens']=None
  await asyncio.gather(*(context_tokens(row) for row in table_rows))
  # Quota recovery retains authenticated row checkpoints only under the owner family policy.
  tables={}
  for row in table_rows:tables.setdefault((row['dataset'],row['mode']),[]).append(row)
  pools=json.loads((REPO/'docs/evals/judge-pools-new-accounts-v1.json').read_text())['new-pool']
  for (dataset,mode),table in tables.items():
   print(json.dumps({'stage':'answer-and-judge','dataset':dataset,'mode':mode,'rows':len(table)}),flush=True)
   answers_complete=False
   for model in config.get('answer_models',['doubao-seed-2-1-pro-260915','mimo-v2.6-flash','minimax-m3']):
    async def answer_one(row):
     if row.get('_answer_checkpoint'):return row['answer'],{'model':row['answer_model'],'usage':row['answer_usage'],'_b0_full_context_truncation':row.get('full_context_truncation')}
     answer,data=await io.answer(row['question'],row['context'],model,row['question_date'],row['system']=='full-context')
     row.update(answer=answer,answer_valid=answer is not None,answer_model=data.get('model'),answer_usage=data.get('usage'),full_context_truncation=data.get('_b0_full_context_truncation'),full_context_truncated=(data.get('_b0_full_context_truncation') or {}).get('truncated',False))
     append(out/'answers-checkpoint-private.jsonl',{**row,'context_sha256':digest(row['context'])})
     return answer,data
    answered=await asyncio.gather(*(answer_one(row) for row in table),return_exceptions=True)
    attempt=[v for v in answered if not isinstance(v,BaseException)];failed=len(attempt)!=len(table)
    append(out/'table-attempts.jsonl',{'dataset':dataset,'mode':mode,'role':'answer','model':model,'completed':len(attempt),'failed':failed,'whole_table':True})
    if failed:continue
    for row,(answer,data) in zip(table,attempt,strict=True):row.update(answer=answer,answer_valid=answer is not None,answer_model=data.get('model'),answer_usage=data.get('usage'),full_context_truncation=data.get('_b0_full_context_truncation'),full_context_truncated=(data.get('_b0_full_context_truncation') or {}).get('truncated',False))
    answers_complete=True;break
   if not answers_complete:raise RuntimeError('EVALUATION_MODEL_QUOTA')
   answer_vendor=vendor(model)
   judge_options=([{'model':config['judge_model'],'vendor':vendor(config['judge_model'])}] if config.get('judge_model') else [pools['primary'],*pools['backups']])
   for judge in judge_options:
    if judge['vendor']==answer_vendor or (dataset=='chinese_queries_v2' and judge['vendor']=='MiniMax'):continue
    async def one_grade(row):
     if row.get('_grade_checkpoint'):return row['judge_correct']
     grade=await io.grade(row,judge['model']) if row['answer_valid'] else None
     row.update(judge_correct=grade,judge_model=judge['model'])
     append(out/'grades-checkpoint-private.jsonl',{**row,'context_sha256':digest(row['context'])})
     return grade
    graded=await asyncio.gather(*(one_grade(row) for row in table),return_exceptions=True)
    attempt=[v for v in graded if not isinstance(v,BaseException)];failed=len(attempt)!=len(table)
    append(out/'table-attempts.jsonl',{'dataset':dataset,'mode':mode,'role':'judge','model':judge['model'],'completed':len(attempt),'failed':failed,'whole_table':True})
    if failed:continue
    for row,grade in zip(table,attempt,strict=True):row.update(judge_correct=grade)
    break
   else:raise RuntimeError('EVALUATION_MODEL_QUOTA')
   write(out/f"table-{dataset}-{mode}-private.json",table)

 try:
  for dataset in names:
   source=REPO/manifest[dataset]['path'];assert file_hash(source)==manifest[dataset]['sha256']
   corpus=rows(source)
   if dataset not in ('dulemon_gold','ecd_negative'):corpus=[c for c in corpus if c['questions']]
   rng=random.Random(seed);rng.shuffle(corpus)
   if dataset.startswith('longmemeval') and config.get('conversations_per_question_type'):
    by_category={}
    for conv in corpus:by_category.setdefault(conv['questions'][0]['category'],[]).append(conv)
    selected=[conv for category in sorted(by_category) for conv in by_category[category][:config['conversations_per_question_type']]]
   else:selected=corpus[:config['conversations_per_dataset'].get(dataset,1)]
   write(out/(dataset+'-selection-private.json'),{'ids':[r['conversation_id'] for r in selected],'source_sha256':file_hash(source),'seed':seed})
   if resume_dataset(dataset,selected):
    write(out/'graded-results-private.json',all_results)
    continue
   for repeat in range(3):
    for mode in (['direct','full'] if args.mode=='both' else [args.mode]):
     finished=await asyncio.gather(*(run_conversation(dataset,conv,mode,repeat) for conv in selected if not resume_conversation(dataset,conv,mode,repeat)),return_exceptions=True)
     errors=[x for x in finished if isinstance(x,BaseException)]
     if errors:raise errors[0]
   await finish_tables([r for r in all_results if r['dataset']==dataset])
   write(out/'graded-results-private.json',all_results)
  write(out/'graded-results-private.json',all_results)
  valid=[r for r in all_results if r['judge_correct'] is not None]
  if len(valid)>=300 and not config.get('offline_fixture'):
   chosen=calibration_sample(valid,300,seed=seed);write(out/'calibration-mapping-private.json',chosen)
   import csv
   with (out/'calibration-300-private.csv').open('w',encoding='utf-8-sig',newline='') as f:
    writer=csv.DictWriter(f,fieldnames=['item_id','question','reference','answer','human_correct','human_reason']);writer.writeheader()
    for i,row in enumerate(chosen):writer.writerow({'item_id':'c-'+digest([seed,row['row_id']])[:20],**{k:__import__('agent_memory.evals.human_review',fromlist=['csv_text']).csv_text(row[k]) for k in ('question','reference','answer')},'human_correct':'','human_reason':''})
   (out/'calibration-300-private.csv').chmod(0o600)
   cross=[]
   try:
    for row in chosen:cross.append({'row_id':row['row_id'],'model':config.get('cross_reference_model','hunyuan-role-latest'),'correct':await io.grade(row,config.get('cross_reference_model','hunyuan-role-latest'),role='cross-reference')});write(out/'cross-reference-private.json',cross)
   except RuntimeError:
    write(out/'cross-reference-incomplete.json',{'completed':len(cross),'required':len(chosen),'model':config.get('cross_reference_model','hunyuan-role-latest'),'reason':'quota; no unqualified cross-reference substitution'})
   status='paused_for_owner_calibration'
  else:status='offline_fixture_completed' if config.get('offline_fixture') else 'incomplete_calibration_population'
 except Exception as error:
  status='runtime_quota_paused' if io.runtime_blocked else 'failed'
  write(out/'failure.json',{'exception_type':type(error).__name__,'reason_code':str(error) if str(error) in ('RUNTIME_QUOTA_PAUSED','EVALUATION_MODEL_QUOTA') else 'details_private','completed_rows':len(all_results)})
  import traceback
  (out/'traceback-private.txt').write_text(traceback.format_exc());(out/'traceback-private.txt').chmod(0o600)
 finally:
  write(out/'status.json',{'status':status,'rows':len(all_results),'model_records_including_replays':len(io.calls),'model_attempts':sum(r.get('new_http_call',not r.get('cache_hit',False)) for r in io.calls),'vector_cache_replays':sum(r.get('cache_hit',False) for r in io.calls),'dev_only':True,'formal_scores':False,'baseline_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=SOURCE,text=True).strip(),'runtime_source':str(SOURCE),'full_evaluation_complete':False,'phase2_accepted':False})
  # Proxy clients belong to their original event loop; shut down proxy before main-loop client.
  await app.state.engine.dispose();server.should_exit=True;thread.join(timeout=5)
  client=io.clients.get(id(asyncio.get_running_loop()))
  if client:await client.aclose()
 print(json.dumps(json.loads((out/'status.json').read_text())),flush=True)


def main():
 p=argparse.ArgumentParser();p.add_argument('--dataset',required=True);p.add_argument('--mode',choices=['direct','full','both'],required=True);p.add_argument('--config',type=Path,required=True);p.add_argument('--metrics',required=True);p.add_argument('--output',type=Path,required=True)
 a=p.parse_args();assert '.local' in a.output.resolve().parts
 catalog=json.loads((REPO/'docs/evals/metric-catalog.json').read_text())
 identifiers={r['id'] for r in catalog};families={r.rstrip('0123456789') for r in identifiers}
 requested=set(a.metrics.split(','))
 if requested-identifiers-families:p.error('unknown metric identifier or family')
 a.expanded_metrics=sorted({mid for mid in identifiers if mid in requested or mid.rstrip('0123456789') in requested})
 config=json.loads(a.config.read_text())
 allowed={'seed','conversations_per_dataset','conversations_per_question_type','questions_per_conversation','system_context_budget','purpose','workload_basis','embedding_cache_roots','datasets_manifest','offline_fixture','extraction_model','extraction_provider','runtime_change_authorization','answer_models','resume_roots','role_accounts','answer_provider','judge_model','judge_provider','embedding_model','embedding_provider','embedding_protocol','cross_reference_provider','four_key_authorization','family_continuation_authorization','cross_reference_model'}
 if set(config)-allowed:p.error('unknown system configuration fields; credentials must use the private environment')
 if config.get('extraction_model','doubao-seed-2-1-pro-260915')!='doubao-seed-2-1-pro-260915' and config.get('runtime_change_authorization')!='om_x100b62846f735ca8df833bd67f54736':p.error('runtime replacement requires the recorded explicit owner authorization')
 if config.get('offline_fixture') and a.dataset!='offline-fixture':p.error('fixture configuration cannot measure actual benchmark data')
 if config.get('datasets_manifest') and not config.get('offline_fixture'):p.error('real runs require frozen dev registry')
 if not config.get('offline_fixture') and config.get('judge_model'):
  answer_vendor=vendor(config.get('answer_models',['doubao-seed-2-1-pro-260915'])[0]);judge_vendor=vendor(config['judge_model'])
  if answer_vendor is None or judge_vendor is None or judge_vendor in {answer_vendor,'DeepSeek','Tencent','MiniMax'}:p.error('judge vendor cannot be verified independent from answer and table annotation vendors')
 a.output.mkdir(parents=True,exist_ok=False,mode=0o700)
 if not config.get('offline_fixture'):
  assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=SOURCE,text=True).strip()==subprocess.check_output(['git','rev-parse','B0^{}'],cwd=REPO,text=True).strip()
  assert not subprocess.check_output(['git','status','--porcelain'],cwd=SOURCE,text=True)
 write(a.output/'run-manifest.json',{'baseline_tag':None if config.get('offline_fixture') else 'B0','baseline_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=SOURCE,text=True).strip(),'harness_uncommitted_changes':bool(subprocess.check_output(['git','status','--porcelain'],cwd=REPO,text=True).strip()),'harness_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip(),'harness_script_sha256':file_hash(Path(__file__)),'harness_support_sha256':{str(p.relative_to(REPO)):file_hash(p) for p in [REPO/'scripts/b0_correctness.py',REPO/'src/agent_memory/evals/b0.py',REPO/'src/agent_memory/evals/metrics.py']},'config':json.loads(a.config.read_text()),'config_sha256':file_hash(a.config),'dataset':a.dataset,'mode':a.mode,'metrics_requested':a.metrics.split(','),'metrics_expanded':a.expanded_metrics,'runtime_application_file':__import__('agent_memory.api.app',fromlist=['x']).__file__,'prompt_hashes':{str(x.relative_to(REPO)):file_hash(x) for x in [*(REPO/'docs/evals/prompts').glob('b0-*'),REPO/'docs/evals/prompts/judge-v1.txt'] if x.is_file()},'seed':42,'dev_only':True,'test_execution':False,'offline_fixture_only':bool(config.get('offline_fixture')),'grade_status':'pre-calibration diagnostic only'})
 with PostgresContainer('pgvector/pgvector:pg16',username='agent_memory',password='disposable-b0-only',dbname='agent_memory',driver='psycopg') as pg:
  url=pg.get_connection_url();cfg=Config(str(SOURCE/'alembic.ini'));cfg.set_main_option('script_location',str(SOURCE/'migrations'));cfg.set_main_option('sqlalchemy.url',url);command.upgrade(cfg,'head')
  engine=create_engine(url)
  with engine.begin() as conn:
   conn.execute(text("CREATE ROLE b0_eval_app LOGIN PASSWORD 'disposable-b0-app-only' NOSUPERUSER NOBYPASSRLS"));conn.execute(text('GRANT agent_memory_app TO b0_eval_app'))
   env={'postgres':conn.scalar(text('SELECT version()')),'pgvector':conn.scalar(text("SELECT extversion FROM pg_extension WHERE extname='vector'")),'image_id':pg.get_wrapped_container().image.id,'non_owner_runtime':True,'mode':'functional in-process public API + disposable actual PostgreSQL; not PF load measurement'}
  write(a.output/'environment.json',env);engine.dispose()
  appurl=make_url(url).set(drivername='postgresql+psycopg_async',username='b0_eval_app',password='disposable-b0-app-only').render_as_string(hide_password=False)
  asyncio.run(measure(a,appurl))
  snapshot=pg.get_wrapped_container().exec_run(['pg_dump','-U','agent_memory','-d','agent_memory','--format=custom'])
  if snapshot.exit_code==0:
   path=a.output/'database-snapshot-private.dump';path.write_bytes(snapshot.output);path.chmod(0o600)
   write(a.output/'database-snapshot-manifest.json',{'sha256':file_hash(path),'bytes':path.stat().st_size,'purpose':'private progress preservation, not a second-machine RL6 restore evaluation'})

if __name__=='__main__':main()
