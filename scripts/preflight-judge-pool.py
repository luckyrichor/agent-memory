"""Small live judge checks. No balance APIs, credentials are environment-only."""
import argparse
import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path
import httpx
from agent_memory.evals import model_preflight
from agent_memory.evals.judge_http import ProviderJudgeRouter
from agent_memory.evals.judge_pool import Judge, JudgeFailure

async def main():
    p=argparse.ArgumentParser()
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--mode',choices=('candidate-preflight','judge-repeat'),required=True)
    a=p.parse_args()
    if '.local' not in a.output.resolve().parts or a.output.exists():
        p.error('new private .local output required; historical evidence is immutable')
    a.output.mkdir(parents=True,mode=0o700)
    if a.mode=='candidate-preflight':
        model_preflight.ARK_MODELS=(*model_preflight.ARK_MODELS,'glm-4-7-251222','mistral-7b-instruct-v0.2')
        for model in ['glm-4-7-251222','glm-5.2','mimo-v2.6-flash','minimax-m2.7','mistral-7b-instruct-v0.2']:
            await model_preflight.run(a.output/('preflight-'+model),
                Path('docs/evals/prompts/preflight-v1.txt'),models=(model,),interval=.6)
        return
    result=[]
    async with httpx.AsyncClient(timeout=60,trust_env=False) as c:
        router=ProviderJudgeRouter(c,Path('docs/evals/prompts/judge-v1.txt').read_text(),{
            'TokenHub':os.getenv('TOKENHUB_API_KEY') or os.getenv('TENCENT_API_KEY',''),
            'Ark':os.getenv('ARK_API_KEY','')},
            os.getenv('TENCENT_BASE_URL','https://tokenhub.tencentmaas.com/v1'))
        for model,vendor,provider in [('glm-5-2-260617','Zhipu','Ark'),
                                      ('hy4-preview','Tencent','TokenHub'),
                                      ('glm-5v-turbo','Zhipu','TokenHub')]:
            rows=[]
            for i in range(5):
                try:
                    g=await router(Judge(model,vendor,True,provider=provider),{
                        'row_id':str(i),'question':'虚构测试人物偏好什么饮品？',
                        'reference':'红茶','answer':'红茶'})
                    rows.append({'valid':True,'score':g.score,'version':g.response_model,'usage':g.usage})
                except JudgeFailure as e:
                    rows.append({'valid':False,'http_status':e.status});break
            result.append({'model':model,'provider':provider,'vendor':vendor,
                'at':datetime.now(UTC).isoformat(),'calls':rows,
                'pass':len(rows)==5 and all(r.get('valid') for r in rows)
                    and len({r.get('score') for r in rows})==1})
            (a.output/'judge-calls.json').write_text(json.dumps(result,indent=2))
            print(json.dumps({'model':model,'pass':result[-1]['pass']}),flush=True)

if __name__=='__main__': asyncio.run(main())
