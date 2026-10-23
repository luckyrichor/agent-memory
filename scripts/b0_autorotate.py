"""Quota-triggered, finite four-key failover. Never changes data, prompts or quality gates."""
import copy,hashlib,json,os,subprocess,sys
from pathlib import Path
import httpx
from b0_accounts import ACCOUNTS,credential
from agent_memory.evals.b0 import measurement_signature,compatible_measurement,FAMILY_CONTINUATION_AUTH
from agent_memory.evals.b0_rotation import candidates,quota,vendor

AUTH='om_x100b6280467a68a4c3cc0005fe78816'

def save(path,value):
 path.parent.mkdir(parents=True,exist_ok=True,mode=0o700);path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n');path.chmod(0o600)

def load(path,default=None):return json.loads(path.read_text()) if path.exists() else default

def ledger(root):
 p=Path(root)/'usage.jsonl'
 if not p.exists():return []
 with p.open() as f:return [json.loads(s) for s in f if s.strip()]

def provider_account(config,role,provider):
 return config.get('role_accounts',{}).get(role,{}).get(provider,'ark-secondary' if provider=='Ark' else 'tokenhub-secondary')

def apply(config,role,provider,account,model):
 result=copy.deepcopy(config);result.setdefault('role_accounts',{}).setdefault(role,{})[provider]=account
 if role=='extraction':result.update(extraction_model=model,extraction_provider=provider)
 elif role=='embedding':result.update(embedding_model=model,embedding_provider=provider,embedding_protocol='ark' if provider=='Ark' and model.startswith('doubao-embedding-vision') else 'openai')
 elif role=='answer':result.update(answer_models=[model],answer_provider=provider);result.setdefault('role_accounts',{}).setdefault('tokenizer',{})[provider]=account
 elif role=='judge':result.update(judge_model=model,judge_provider=provider)
 elif role=='cross-reference':result.update(cross_reference_provider=provider,cross_reference_model=model)
 return result

class Rotation:
 def __init__(self,root,config):
  self.root=root;self.root.mkdir(parents=True,exist_ok=True,mode=0o700);self.unavailable=set();self.catalog=None;self.qualifications={}
  histories=set(config.get('embedding_cache_roots',[])+config.get('resume_roots',[]))
  for path in histories:
   for r in ledger(path):
    if quota(r):self.unavailable.add((r.get('account','ark-secondary' if r.get('provider')=='Ark' else 'tokenhub-secondary'),r['model']))
 def models(self):
  if self.catalog is not None:return self.catalog
  result={'Ark':[],'TokenHub':[]}
  for account,(provider,_file,_key) in ACCOUNTS.items():
   p=self.root/f'catalog-{account}.json'
   try:
    if p.exists():record=load(p)
    else:
     _provider,base,token=credential(account)
     with httpx.Client(timeout=30,trust_env=False) as client:response=client.get(base+'/models',headers={'Authorization':'Bearer '+token})
     data=response.json();record={'account':account,'provider':provider,'http':response.status_code,'models':[r['id'] for r in data.get('data',[]) if isinstance(r,dict) and isinstance(r.get('id'),str)],'not_a_quota_or_permission_claim':True};save(p,record)
    if record.get('http')==200:result[provider].extend(record['models'])
   except (OSError,ValueError,KeyError,httpx.HTTPError):save(p,{'account':account,'provider':provider,'status':'catalog_unavailable','not_a_balance_claim':True})
  self.catalog={p:sorted(set(ids)) for p,ids in result.items()};return self.catalog
 def qualify(self,profile,role,provider,account,model):
  key=(role,account,model)
  if key in self.qualifications:return self.qualifications[key]
  number=len(list(self.root.glob('qualification-*')));root=self.root/f'qualification-{number:04d}';root.mkdir(mode=0o700);profile_path=root/'profile-private.json';save(profile_path,profile)
  passed=False
  try:
   generic=True
   if role!='embedding':
    # Reuse only the explicitly recorded fresh key/model preflight, not another account's success.
    existing=Path('.local/phase2/b0/four-key-policy-v1/primary-lite-preflight/summary.json')
    record=load(existing,{})
    if not (account=='ark-primary' and model=='doubao-seed-2-1-lite-260915' and record.get('passed') and record.get('account')==account):
     subprocess.run([sys.executable,'scripts/with-llm-account.py',account,sys.executable,'scripts/preflight-b0-policy.py','--model',model,'--provider',provider,'--output',str(root/'generic')],check=False)
     record=load(root/'generic/summary.json',{})
    generic=bool(record.get('passed'));save(root/'generic-summary.json',record)
   if generic:
    subprocess.run([sys.executable,'scripts/qualify-b0-role.py','--profile',str(profile_path),'--role',role,'--output',str(root/'native-role')],check=False)
    passed=bool(load(root/'native-role/summary.json',{}).get('passed'))
  except (OSError,ValueError,KeyError):passed=False
  self.qualifications[key]=passed;save(root/'decision.json',{'role':role,'account':account,'model':model,'provider':provider,'passed':passed,'quality_gates_unchanged':True});return passed
 def next(self,config,run,history,status):
  if config.get('four_key_authorization')!=AUTH:return None
  if (self.root/'STOP').exists():return None
  cross=(run/'cross-reference-incomplete.json').exists()
  failure=load(run/'failure.json',{})
  if not (status.get('status')=='runtime_quota_paused' or (status.get('status')=='failed' and failure.get('reason_code')=='EVALUATION_MODEL_QUOTA') or (status.get('status')=='paused_for_owner_calibration' and cross)):return None
  event=load(run/'runtime-quota-pause.json',{})
  cross=(run/'cross-reference-incomplete.json').exists()
  if not event:
   failures=[r for r in ledger(run) if quota(r)]
   if cross:
    failures=[r for r in failures if r['role']=='cross-reference']
   if failures:event=failures[-1]
  if not event or not quota(event):return None
  role=event['role']
  if role not in ('extraction','embedding','answer','judge','cross-reference'):return None
  provider=event['provider'];model=event['model'];account=event.get('account',provider_account(config,role,provider));self.unavailable.add((account,model))
  save(self.root/'unavailable-model-accounts.json',{'pairs':sorted(self.unavailable),'scope':'actual quota responses only; not all-model balance conclusions'})
  catalog=self.models()
  options=candidates(role,model,provider,catalog,self.unavailable,answer_vendor=vendor(config.get('answer_models',['doubao-seed-2-1-pro-260915'])[0]),judge_vendor=vendor(config.get('judge_model','glm-5.2')))
  if config.get('family_continuation_authorization')==FAMILY_CONTINUATION_AUTH:
   if role=='cross-reference':
    options=[o for o in candidates('answer',model,provider,catalog,self.unavailable,answer_vendor=vendor(config.get('answer_models',['doubao-seed-2-1-pro-260915'])[0]),judge_vendor=vendor(config.get('judge_model','glm-5.2'))) if vendor(o[2])==vendor(model)]
   options.sort(key=lambda option:(option[2]!=model, vendor(option[2])!=vendor(model)))
  for new_provider,new_account,new_model in options:
   updated=apply(config,role,new_provider,new_account,new_model)
   if not self.qualify(updated,role,new_provider,new_account,new_model):continue
   # The same capped model/account cannot remain the answer role after extraction moves.
   if role=='extraction' and config.get('answer_models',['doubao-seed-2-1-pro-260915'])[0]==model and provider_account(config,'answer',config.get('answer_provider','Ark'))==account:
    if vendor(new_model)==vendor(config.get('judge_model','glm-5.2')):continue
    updated=apply(updated,'answer',new_provider,new_account,new_model)
    if not self.qualify(updated,'answer',new_provider,new_account,new_model):continue
   changed=measurement_signature(updated)!=measurement_signature(config)
   compatible=compatible_measurement(config,updated)
   updated['resume_roots']=[] if not compatible else list(dict.fromkeys([str(run),*config.get('resume_roots',[])]))
   if role=='embedding' and changed:updated['embedding_cache_roots']=[]
   else:updated['embedding_cache_roots']=list(dict.fromkeys([*config.get('embedding_cache_roots',[]),*map(str,history)]))
   updated['purpose']='owner-authorized continuation: same chat family retains verified completed work; different family or vector space restarts comparison'
   save(self.root/f'rotation-{len(list(self.root.glob("rotation-*.json"))):04d}.json',{'role':role,'old_provider':provider,'old_account':account,'old_model':model,'provider':new_provider,'account':new_account,'model':new_model,'measurement_profile_changed':changed,'complete_comparison_restarted':not compatible,'same_family_continuation':changed and compatible,'owner_authorization':config.get('family_continuation_authorization'),'credential_values_logged':False})
   return updated
  save(self.root/'no-qualified-candidate.json',{'role':role,'considered':len(options),'status':'no eligible qualified candidate in discovered catalog and four configured keys','not_all_models_balance_exhausted_claim':True});return None
