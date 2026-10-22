import importlib.util
import json
from pathlib import Path

import httpx
import pytest


def load_cli():
    spec = importlib.util.spec_from_file_location(
        'evidence_v3_replacement_test', 'scripts/run-evidence-v3-replacement.py'
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
@pytest.mark.parametrize('model,host,key', [
    ('deepseek-v4-pro-ga-260813', 'ark.cn-beijing.volces.com', 'mock-ark-not-real'),
    ('hy4-preview', 'tokenhub.tencentmaas.com', 'mock-tencent-not-real'),
])
async def test_replacement_routes_credentials_and_validates_user_quote(monkeypatch, tmp_path, model, host, key):
    module = load_cli()
    monkeypatch.setattr(module, 'ROOT', tmp_path / '.local')
    prompt = tmp_path / 'prompt.txt'
    prompt.write_text('mock evidence protocol')
    monkeypatch.setattr(module, 'PROMPT', prompt)
    monkeypatch.setenv('ARK_API_KEY', 'mock-ark-not-real')
    monkeypatch.setenv('TOKENHUB_API_KEY', 'mock-tencent-not-real')
    monkeypatch.setenv('TENCENT_BASE_URL', 'https://tokenhub.tencentmaas.com/v1')
    original = httpx.AsyncClient
    calls = []

    def respond(request):
        assert request.url.host == host
        assert request.headers['Authorization'] == 'Bearer ' + key
        body = json.loads(request.content)
        assert body['model'] == model and body['temperature'] == 0
        assert body['thinking'] == {'type': 'disabled'}
        wire = json.loads(body['messages'][1]['content'])
        assert 'human_label' not in wire['items'][0]
        from agent_memory.evals.evidence_v3 import DIMENSIONS
        evidence = {k: [] for k in DIMENSIONS}
        for k in ('subject', 'relation'):
            evidence[k] = [{'detail':'喜欢画画','source_id':'u','quote':'我喜欢画画'}]
        calls.append(body)
        return httpx.Response(200, json={
            'model':model, 'choices':[{'finish_reason':'stop', 'message':{'content':json.dumps({
                'labels':[{'item_id':'i0','label':'keep','reason':'supported','evidence':evidence}]
            })}}], 'usage':{'total_tokens':1,'completion_tokens_details':{'reasoning_tokens':0}},
        })

    monkeypatch.setattr(module.httpx, 'AsyncClient',
                        lambda **kw: original(**kw, transport=httpx.MockTransport(respond)))
    # No actual sleeping is needed for mocked calls.
    async def no_sleep(_):
        pass
    monkeypatch.setattr(module.asyncio, 'sleep', no_sleep)
    item = {'item_id':'original','conversation_id':'c','subject':'user','candidate':'喜欢画画',
            'source':[{'source_id':'u','role':'user','text':'我喜欢画画'}]}
    assert await module.run_model('preflight', model, [item])
    assert len(calls) == 1
    path = module.ROOT / 'preflight' / model / 'checked.jsonl'
    row = json.loads(path.read_text())
    assert row['item_id'] == 'original' and row['label'] == 'keep' and row['citation_valid']
    assert await module.run_model('preflight', model, [item])
    assert len(calls) == 1  # completed responses replay without spending tokens


@pytest.mark.asyncio
async def test_no_replacement_full_batch_without_offline_gate():
    module = load_cli()
    module.report = lambda: {'offline_passed': False}
    with pytest.raises(ValueError, match='offline gate'):
        await module.full()


def test_replacement_keeps_original_split_and_new_pair_scope():
    module = load_cli()
    assert module.MODELS == ('deepseek-v4-pro-ga-260813', 'hy4-preview')
    assert module.ROOT != Path('.local/phase1/round3/evidence-v3')
