"""Synthetic correctness observations against the frozen B0 public API.

These are deterministic adversarial fixtures, not public benchmark quality data.
No real provider calls; no runtime source modifications.
"""
import asyncio,json
from dataclasses import replace
from datetime import datetime,timezone,timedelta
from pathlib import Path
from uuid import uuid4

import httpx,jwt
from sqlalchemy import text
from agent_memory.domain.enums import MemoryStatus,MemoryType,ScopeKind
from agent_memory.domain.models import Memory,MemoryScope
from agent_memory.domain.errors import InvalidStatusTransition
from agent_memory.domain.principal import RequestPrincipal
from agent_memory.infrastructure.db import session_for_principal
from agent_memory.evals.metrics import ratio


def estimate(numerator,denominator):
 return ratio([(float(numerator),float(denominator))]).to_dict()


async def measure_correctness(app,sessions,key,out,runtime_label='B0'):
 observed=[];at=datetime.now(timezone.utc)
 allowed={'active':{'archived','invalidated','superseded','deleted'},'archived':{'active','invalidated','superseded','deleted'},'invalidated':{'deleted'},'superseded':{'deleted'},'candidate':{'deleted'},'needs_review':{'deleted'},'rejected':{'deleted'},'deleted':set()}
 memory,_=Memory.create(tenant_id=uuid4(),memory_id=uuid4(),version_id=uuid4(),memory_type=MemoryType.EPISODIC,scope=MemoryScope(ScopeKind.WORKSPACE,'fixture',None),owner_user_id=uuid4(),content='synthetic harmless correctness fixture',now=at)
 illegal=[]
 for old in MemoryStatus:
  for new in MemoryStatus:
   if new.value in allowed[old.value]:continue
   rejected=False
   try:replace(memory,status=old).disable(new,at,uuid4())
   except InvalidStatusTransition:rejected=True
   illegal.append((float(rejected),1.0))
 observed.append({'id':'LC5','dataset':'synthetic exhaustive enum transition matrix','scale':len(illegal),'method':'enumerate every disallowed status pair against frozen Memory.disable; successor supplied so missing successor cannot mask illegal transitions','baseline':runtime_label,'estimate':ratio(illegal).to_dict(),'repeats':1,'scope':'finite exhaustive domain matrix; degenerate bootstrap does not infer general request correctness'})
 def token(tenant,user,permissions):
  return jwt.encode({'iss':'b0-eval','aud':'b0-eval','sub':str(user),'tenant_id':str(tenant),'roles':['developer'],'permissions':permissions,'allowed_workspace_ids':['fixture'],'exp':datetime.now(timezone.utc)+timedelta(hours=2)},key,algorithm='RS256')
 for repeat in range(3):
  tenant,user=uuid4(),uuid4();auth={'Authorization':'Bearer '+token(tenant,user,['memory:read','memory:write','memory:delete'])}
  body={'content':'Synthetic stable preference for a dark console.','memory_type':'semantic','scope':{'kind':'workspace','workspace_id':'fixture'}}
  async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://b0-correctness') as client:
   replay=await asyncio.gather(*(client.post('/v1/memories',json=body,headers={**auth,'Idempotency-Key':'fixture-same'}) for _ in range(100)))
   valid=[r.json() for r in replay if r.status_code in (200,201)];ids={r['memory_id'] for r in valid}
   conflict=await client.post('/v1/memories',json={**body,'content':'A different synthetic payload.'},headers={**auth,'Idempotency-Key':'fixture-same'})
   observed.append({'id':'RL1','dataset':'synthetic concurrent idempotency fixture','scale':len(replay)+1,'repeat':repeat,'method':'100 concurrent identical requests plus same key different body','baseline':runtime_label,'duplicate_memory_count':max(0,len(ids)-1),'same_key_different_body_http':conflict.status_code,'invalid_http':sum(r.status_code not in (200,201) for r in replay),'success_responses':len(valid),'all_consistent':len(ids)==1 and len(valid)==100 and conflict.status_code==409})
   if not valid:continue
   mid=valid[0]['memory_id'];rev=valid[0]['revision']
   corrections=await asyncio.gather(*(client.post(f'/v1/memories/{mid}/versions',headers=auth,json={'expected_revision':rev,'content':f'Synthetic concurrent correction {i}.','reason':'fixture'}) for i in range(20)))
   success=[r for r in corrections if r.status_code==201]
   observed.append({'id':'RL2','dataset':'synthetic compare-and-swap fixture','scale':len(corrections),'repeat':repeat,'method':'20 concurrent corrections with same expected_revision','baseline':runtime_label,'successful_mutations':len(success),'conflicts':sum(r.status_code==409 for r in corrections),'lost_update_count':max(0,len(success)-1),'unexpected_http':sum(r.status_code not in (201,409) for r in corrections)})
   other={'Authorization':'Bearer '+token(uuid4(),uuid4(),['memory:read','memory:write','memory:delete'])}
   get=await client.get(f'/v1/memories/{mid}',headers=other)
   mutation=await client.post(f'/v1/memories/{mid}/versions',headers=other,json={'expected_revision':rev,'content':'Synthetic adversarial correction.','reason':'fixture'})
   observed.append({'id':'SC1','dataset':'synthetic cross-tenant known-ID fixture','scale':2,'repeat':repeat,'method':'non-owner API principal attempts foreign known-ID read and write; no successful response allowed','baseline':runtime_label,'cross_tenant_successes':sum(200<=r.status_code<300 for r in (get,mutation)),'http_statuses':[get.status_code,mutation.status_code]})
   limited={'Authorization':'Bearer '+token(tenant,user,[])}
   denied=[await client.get(f'/v1/memories/{mid}',headers=limited),await client.post('/v1/memories',headers={**limited,'Idempotency-Key':'fixture-no-permission'},json=body),await client.post('/v1/memories/search',headers=limited,json={'query':'fixture'})]
   observed.append({'id':'SC3','dataset':'synthetic permission-denied fixture','scale':len(denied),'repeat':repeat,'method':'valid JWT with empty permission set tries read/write/search','baseline':runtime_label,'unauthorized_successes':sum(200<=r.status_code<300 for r in denied),'explicit_forbidden':sum(r.status_code==403 for r in denied),'http_statuses':[r.status_code for r in denied]})
   if success:
    current=success[0].json();deletion=await client.post('/v1/deletion-requests',headers={**auth,'Idempotency-Key':'fixture-delete'},json={'memory_id':mid,'expected_revision':current['revision']})
    principal=RequestPrincipal(tenant,user,frozenset({'developer'}),frozenset({'memory:read'}),frozenset({'fixture'}))
    async with session_for_principal(sessions,principal) as session:
     remaining=await session.scalar(text('SELECT count(*) FROM memory_versions WHERE tenant_id=:tenant AND memory_id=:memory'),{'tenant':tenant,'memory':mid})
    observed.append({'id':'LC7','dataset':'synthetic logical deletion residue fixture','scale':1,'repeat':repeat,'method':'public logical delete, then internal observation of retained version rows','baseline':runtime_label,'delete_http':deletion.status_code,'retained_body_versions':remaining,'residue_zero':remaining==0,'scope':'body versions only; vectors/events/index/backup residue not fully inspected, so not full deletion completeness; known B0 pending physical cleanup boundary, not a newly introduced optimization regression'})
 observed.extend(await measure_filter_controls(app,sessions,key,runtime_label))
 target=out/'correctness-observations.json';target.write_text(json.dumps({'data_level':'C synthetic functional correctness; not semantic quality','runtime_commit':runtime_label,'observations':observed,'model_calls':0,'other_correctness_metrics':'unmeasured; do not infer passing from missing adapter','LC7_full_completion_claim':False},ensure_ascii=False,indent=2)+'\n');target.chmod(0o600)
 return observed


async def measure_filter_controls(app,sessions,key,runtime_label):
 from uuid import UUID
 from agent_memory.infrastructure.orm import MemoryEmbeddingRow
 vector=[1.0]+[0.0]*1023;observed=[]
 for repeat in range(3):
  tenant,user=uuid4(),uuid4();records={}
  def headers(tid,uid,workspaces):
   return {'Authorization':'Bearer '+jwt.encode({'iss':'b0-eval','aud':'b0-eval','sub':str(uid),'tenant_id':str(tid),'roles':['developer'],'permissions':['memory:read','memory:write','memory:archive','memory:invalidate','memory:supersede'],'allowed_workspace_ids':workspaces,'exp':datetime.now(timezone.utc)+timedelta(hours=1)},key,algorithm='RS256')}
  caller=headers(tenant,user,['public'])
  async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://b0-filter-control') as client:
   for name,tid,uid,workspace,scope,memory_type in [('allowed',tenant,user,'public','workspace','semantic'),('tenant',uuid4(),user,'public','workspace','semantic'),('workspace',tenant,user,'private','workspace','semantic'),('user',tenant,uuid4(),None,'user_global','semantic'),('review',tenant,user,None,'tenant','procedural'),('archived',tenant,user,'public','workspace','semantic'),('invalidated',tenant,user,'public','workspace','semantic'),('superseded',tenant,user,'public','workspace','semantic')]:
    body_scope={'kind':scope}
    if workspace:body_scope['workspace_id']=workspace
    if scope=='user_global':body_scope['subject_user_id']=str(uid)
    created=await client.post('/v1/memories',headers={**headers(tid,uid,[workspace] if workspace else []),'Idempotency-Key':str(uuid4())},json={'content':'compiler '+name,'memory_type':memory_type,'scope':body_scope})
    if created.status_code!=201:raise RuntimeError('FILTER_FIXTURE_CREATE_FAILED')
    record=created.json();records[name]=record
    principal=RequestPrincipal(tid,uid,frozenset(),frozenset({'memory:write'}),frozenset([workspace] if workspace else []))
    async with session_for_principal(sessions,principal) as session:
     session.add(MemoryEmbeddingRow(tenant_id=tid,memory_version_id=UUID(record['version_id']),model='guard-fixture',embedding=vector,updated_at=datetime.now(timezone.utc)))
   query={'query':'compiler','vector':vector,'model':'guard-fixture','workspace_id':'public','limit':20}
   before=await client.post('/v1/memories/search',headers=caller,json=query)
   if before.status_code!=200:raise RuntimeError('FILTER_FIXTURE_QUERY_FAILED')
   before_ids={r['memory_id'] for r in before.json()['items']}
   controls=('archived','invalidated','superseded')
   setup_valid=all(records[n]['memory_id'] in before_ids for n in ('allowed',*controls))
   actions=[]
   for name in controls:
    action={'archived':'archive','invalidated':'invalidate','superseded':'supersede'}[name];body={'expected_revision':1}
    if action=='supersede':body['successor_id']=records['allowed']['memory_id']
    response=await client.post(f"/v1/memories/{records[name]['memory_id']}/{action}",headers=caller,json=body);actions.append(response.status_code)
   after=await client.post('/v1/memories/search',headers=caller,json=query)
   if after.status_code!=200:raise RuntimeError('FILTER_FIXTURE_QUERY_FAILED')
   ids={r['memory_id'] for r in after.json()['items']};setup_valid=setup_valid and all(s==200 for s in actions) and records['allowed']['memory_id'] in ids
   expired=sum(records[n]['memory_id'] in ids for n in controls);foreign=sum(records[n]['memory_id'] in ids for n in ('tenant','workspace','user'))
   common={'dataset':'C synthetic all-channel filtering fixture','repeat':repeat,'baseline':runtime_label,'method':'public API, non-owner PostgreSQL; explicitly supplied synthetic 1024d vector and controlled derived rows only for structural filtering, not semantic model quality or PF','setup_valid':setup_valid,'model_calls':0}
   observed.append({**common,'id':'LC4','scale':1,'expired_status_cases':len(controls),'expired_memories_returned':expired,'leak_queries':int(expired>0) if setup_valid else None,'denominator_queries':1 if setup_valid else 0,'actions_http':actions})
   observed.append({**common,'id':'RT10','scale':3,'forbidden_returned':foreign if setup_valid else None,'channel_counts_after':after.json()['channel_counts'],'review_pending_returned':records['review']['memory_id'] in ids})
 return observed
