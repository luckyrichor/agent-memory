"""Export loader-compatible technical pools; formal scoring still requires owner calibration."""
import json
from pathlib import Path

from agent_memory.evals.evidence_v3 import sha
from agent_memory.evals.table_pool import load_table_pool


def main():
    public = Path('docs/evals/judge-pools-new-accounts-v1.json')
    pools = json.loads(public.read_text())
    output = Path('.local/phase1/round3/new-accounts-v1/judge-runtime-freezes')
    output.mkdir(parents=True,exist_ok=True,mode=0o700)
    policy = {
        'judge_minimum_backups':1,
        'tables':{name:{'answer_vendor':'ByteDance','annotation_vendors':value['annotation_vendors']} for name,value in pools.items()},
        'judge_vendors':{},
        'withdrawn_judges':{'TokenHub:glm-5v-turbo':'pre-offline','TokenHub:youtu-vita':'discontinued'},
        'human_calibration_required':True,'formal_scores_currently_allowed':False,
    }
    policy_path = Path('docs/evals/judge-new-accounts-policy-v1.json')
    for value in pools.values():
        for row in ([value['primary']] if value['primary'] else [])+value['backups']:
            policy['judge_vendors'][row['provider']+':'+row['model']]=row['vendor']
    policy_path.write_text(json.dumps(policy,ensure_ascii=False,indent=2)+'\n')
    proof=[]
    for name,pool in pools.items():
        candidates=[]
        for row in ([pool['primary']] if pool['primary'] else [])+pool['backups']:
            original=Path(row['actual_call_path']);actual=json.loads(original.read_text())
            assert actual['passed'] and actual['generic_preflight_sha256']==sha(Path(row['preflight_path']))
            normalized=output/(row['account']+'-'+row['model']+'-actual.json')
            normalized.write_text(json.dumps({'model':row['model'],'provider':row['provider'],'at':actual['at'],'pass':actual['passed'],'original_actual_call_sha256':sha(original),'account':row['account']},indent=2)+'\n')
            candidates.append({k:row[k] for k in ('model','vendor','provider','account')} | {
                'preflight':{'path':row['preflight_path'],'sha256':sha(Path(row['preflight_path']))},
                'actual_call':{'path':str(normalized),'sha256':sha(normalized)},'calibration':None,
            })
        config={'table_kind':name,'roles':policy['tables'][name],'policy_path':str(policy_path),'policy_sha256':sha(policy_path),'judge_prompt_sha256':sha(Path('docs/evals/prompts/judge-v1.txt')),'candidates':candidates}
        path=output/(name+'.json');path.write_text(json.dumps(config,ensure_ascii=False,indent=2)+'\n')
        try:
            load_table_pool(config,policy,name)
        except ValueError as error:
            assert str(error)=='owner calibration missing for primary or backup',str(error)
            proof.append({'table':name,'technical_pool_exported':True,'formal_scoring_blocked_until_owner_calibration':True,'path':str(path),'sha256':sha(path)})
        else:
            raise AssertionError('uncalibrated pool must never permit formal scoring')
    (output/'verification.json').write_text(json.dumps(proof,indent=2)+'\n')
    print(json.dumps(proof))


if __name__=='__main__':
    main()
