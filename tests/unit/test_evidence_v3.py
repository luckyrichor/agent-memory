import pytest

from agent_memory.evals.evidence_v3 import (
    DIMENSIONS,
    EvidenceLabel,
    gate,
    grouped_split,
    metrics,
    validate_quotes,
)


def sample(source_id="u", quote="我喜欢画画", role="user", text="我喜欢画画"):
    evidence = {k: [] for k in DIMENSIONS}
    for k in ("subject", "relation"):
        evidence[k] = [{"detail": "喜欢画画", "source_id": source_id, "quote": quote}]
    label = EvidenceLabel.model_validate({
        "item_id": "i", "label": "keep", "reason": "supported", "evidence": evidence,
    })
    item = {"item_id": "i", "source": [{"source_id": "u", "role": role, "text": text}]}
    return label, item


@pytest.mark.parametrize("options,code", [
    ({"source_id": "missing"}, "unknown-source-id"),
    ({"role": "assistant"}, "not-user-source"),
    ({"quote": "我最喜欢画画"}, "quote-not-exact-substring"),
    ({"quote": "我喜欢…画画"}, "quote-not-exact-substring"),
    ({"quote": " "}, "empty-citation"),
])
def test_invalid_quote_downgrades_keep(options, code):
    result = validate_quotes(*sample(**options))
    assert result["label"] == "uncertain" and code in result["citation_failures"]


def test_exact_quote_retained_without_semantic_proxy():
    assert validate_quotes(*sample())["label"] == "keep"
    # Mechanical checker deliberately cannot detect semantic errors or omitted details.
    assert validate_quotes(*sample(quote="喜欢", text="我不喜欢画画"))["citation_valid"]


def test_duplicate_source_is_not_silently_resolved():
    label, item = sample()
    item["source"].append(item["source"][0])
    with pytest.raises(ValueError, match="duplicate"):
        validate_quotes(label, item)


def test_missing_subject_or_relation_evidence_fails_closed():
    label, item = sample()
    label.evidence.relation.clear()
    assert validate_quotes(label, item)["label"] == "uncertain"


def test_split_groups_conversations_and_replays():
    items = {str(k): {"conversation_id": str(k // 2)} for k in range(40)}
    groups = {k: "blind72-keep" if int(k) % 3 else "blind72-discard" for k in items}
    split = grouped_split(items, groups)
    assert split == grouped_split(items, groups)
    assert split["conversation_overlap"] == 0
    assert set(split["development"]).isdisjoint(split["final"])
    assert set(split["development"] + split["final"]) == items.keys()


def test_no_failed_calls_counted_as_successful_error_blocks():
    groups = {"a": "blind72-discard", "b": "blind72-keep", "c": "native157-keep"}
    result = metrics({}, groups, list(groups))
    assert result["blind72-discard"]["rate"] is None
    assert not gate(result)


@pytest.mark.asyncio
async def test_quota_blocks_final_set_and_full_relabel(monkeypatch, tmp_path):
    import importlib.util
    import json
    from pathlib import Path

    import httpx

    path = Path('scripts/run-evidence-v3.py')
    spec = importlib.util.spec_from_file_location('evidence_v3_cli_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    root = tmp_path / '.local' / 'run'
    root.mkdir(parents=True)
    (root / 'split-private.json').write_text(json.dumps({'development': ['i'], 'final': ['j']}))
    prompt = root / 'prompt.txt'
    prompt.write_text('mock protocol')
    item = {'item_id': 'i', 'conversation_id': 'c', 'subject': 'user',
            'candidate': 'synthetic', 'source': [{'source_id': 'u', 'role': 'user', 'text': 'mock'}]}
    monkeypatch.setattr(module, 'ROOT', root)
    monkeypatch.setattr(module, 'PROMPT', prompt)
    monkeypatch.setattr(module, 'verify', dict)
    monkeypatch.setattr(module, 'inputs', lambda: ({'i': item, 'j': {**item, 'item_id': 'j'}}, {}, {}))
    monkeypatch.setattr(module, 'report', lambda: {'offline_passed': False})
    monkeypatch.setenv('TOKENHUB_API_KEY', 'mock-not-real')
    calls = []

    def respond(request):
        calls.append(json.loads(request.content))
        return httpx.Response(402, json={'error': {'code': '401008'}})

    original = httpx.AsyncClient
    monkeypatch.setattr(module.httpx, 'AsyncClient',
                        lambda **kw: original(**kw, transport=httpx.MockTransport(respond)))
    await module.offline()
    assert len(calls) == 2
    assert not (root / 'final').exists()
    assert not (root / 'full').exists()
    assert all(set(json.loads(c['messages'][1]['content'])) == {'sources', 'items'} for c in calls)
    # Rerunning without explicit failure recovery cannot consume more calls or inspect holdout.
    await module.offline()
    assert len(calls) == 2
    with pytest.raises(ValueError, match='gate not passed'):
        await module.full()
