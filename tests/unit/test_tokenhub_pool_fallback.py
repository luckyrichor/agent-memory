import hashlib
import importlib.util
import json

import httpx
import pytest


def load(path, name):
    spec = importlib.util.spec_from_file_location(name,path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
@pytest.mark.parametrize('model,json_mode', [('deepseek-v4.1-flash-1017',False),('hy4-preview',True)])
async def test_optional_json_mode_adaptation_keeps_actual_request_hash_and_validator(monkeypatch,tmp_path,model,json_mode):
    engine = load('scripts/tokenhub-pool-annotation-engine.py','tokenhub_pool_test')
    from agent_memory.evals.evidence_v3 import DIMENSIONS
    root = tmp_path / '.local'
    prompt = tmp_path / 'prompt.txt'
    prompt.write_text('fictitious v3 protocol')
    monkeypatch.setattr(engine,'ROOT',root)
    monkeypatch.setattr(engine,'PROMPT',prompt)
    monkeypatch.setenv('TOKENHUB_API_KEY','mock-not-real')
    monkeypatch.setenv('TENCENT_BASE_URL','https://tokenhub.tencentmaas.com/v1')
    calls = []
    original = httpx.AsyncClient

    def reply(request):
        body = json.loads(request.content)
        calls.append(body)
        assert request.url.host == 'tokenhub.tencentmaas.com'
        assert ('response_format' in body) == json_mode
        assert body['temperature'] == 0 and body['thinking'] == {'type':'disabled'}
        ev = {k:[] for k in DIMENSIONS}
        for k in ('subject','relation'):
            ev[k] = [{'detail':'喜欢集邮','source_id':'u','quote':'我喜欢集邮'}]
        return httpx.Response(200,json={'model':model,'choices':[{'finish_reason':'stop','message':{'content':json.dumps({
            'labels':[{'item_id':'i0','label':'keep','reason':'supported','evidence':ev}]
        })}}],'usage':{'total_tokens':1,'completion_tokens_details':{'reasoning_tokens':0}}})

    monkeypatch.setattr(engine.httpx,'AsyncClient',lambda **kw:original(**kw,transport=httpx.MockTransport(reply)))
    async def sleep(_):
        pass
    monkeypatch.setattr(engine.asyncio,'sleep',sleep)
    row = {'item_id':'original','conversation_id':'c','subject':'user','candidate':'喜欢集邮',
           'source':[{'source_id':'u','role':'user','text':'我喜欢集邮'}]}
    assert await engine.run_model('pool-shard-0',model,[row])
    directory = root / 'pool-shard-0' / model
    ledger = json.loads((directory/'ledger.json').read_text())[0]
    assert ledger['request_sha256'] == hashlib.sha256(json.dumps(calls[0],sort_keys=True).encode()).hexdigest()
    assert json.loads((directory/'checked.jsonl').read_text())['citation_valid']
    # Full completed same-model response is replayed, no second API call.
    assert await engine.run_model('pool-shard-0',model,[row])
    assert len(calls) == 1


def test_fallback_does_not_export_blind_audit_from_partial_replacement(monkeypatch,tmp_path):
    runner = load('scripts/run-tokenhub-pool-fallback.py','fallback_partial_test')
    root = tmp_path / '.local'
    root.mkdir()
    (root/'pool-items.jsonl').write_text(json.dumps({'item_id':'i'})+'\n')
    monkeypatch.setattr(runner,'root',lambda:root)
    monkeypatch.setattr(runner,'verify',dict)
    monkeypatch.setattr(runner,'engine',lambda:None)
    with pytest.raises(ValueError,match='side incomplete'):
        runner.finalize()
    assert not (root/'audit72').exists()


@pytest.mark.parametrize('http,code,expected',[(402,'401008',True),(429,'SetLimitExceeded',True),(429,'RateLimitExceeded',False),(200,None,False)])
@pytest.mark.parametrize('model_dir',['model','deepseek/deepseek-flash'])
def test_only_quota_failure_rotates_whole_annotation_side(tmp_path,http,code,expected,model_dir):
    orchestrator = load('scripts/continue-pool-with-quota-fallback.py','quota_rotation_test')
    folder = tmp_path / 'pool-shard-0' / model_dir
    folder.mkdir(parents=True)
    (folder/'ledger.json').write_text(json.dumps([{'status':'failed','offset':0,'http_status':http}]))
    (folder/'0000-response.json').write_text(json.dumps({'error':{'code':code}}))
    assert orchestrator.quota_blocked(tmp_path) is expected
