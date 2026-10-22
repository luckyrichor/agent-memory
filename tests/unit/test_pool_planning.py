import csv
import json

import pytest

from agent_memory.evals.approved_audit import FIELDS, prepare_joint_audit
from agent_memory.evals.pool_planning import production_scenario, source_record


def test_required_fields_are_the_actual_both_schema():
    row = {'conversation':['Usr:我 喜 欢 集 邮\tu1','Bot:你好'],
           'user_said_persona':['u:喜欢集邮'], 'user_no_said_persona':['u:喜欢骑马']}
    h, n, error = source_record(row)
    assert h and n == 2 and error is None
    # Annotation tabs and segmentation cannot conceal identical dialogue text.
    duplicate = {**row, 'conversation':['Usr:我喜欢集邮\tdifferent','Bot:你好']}
    assert source_record(duplicate)[0] == h
    assert source_record({'conversation':row['conversation'],'p1_persona':[]})[2] == 'missing-persona-field'
    assert source_record({**row,'conversation':['Someone:hello']})[2] == 'invalid-speaker-or-text'


def test_planning_is_conditional_and_rounds_calls_up():
    result = production_scenario(gap=615,candidates_per_dialogue=5.5,
                                 candidate_survival=.2,precision_assumption=.95)
    assert result['dialogues_estimated'] * 5.5 * .2 * .95 >= 615
    assert result['calls_both_models'] == 2 * result['calls_each_model']
    assert result['calls_each_model'] * 8 >= result['candidate_reviews_each_model']
    assert result['manual_positive_confirmations_required_for_individual_gold'] == 615
    assert result['conditional_only'] and not result['gold_adopted']
    assert result['tokens_both_models_estimated'] is None


@pytest.mark.parametrize('survival',[0, -1, 1.5])
def test_no_fabricated_forecast_with_zero_or_invalid_survival(survival):
    with pytest.raises(ValueError):
        production_scenario(gap=1,candidates_per_dialogue=2,candidate_survival=survival,
                            precision_assumption=.95)


def test_pool_audit_projects_global_exclusions_then_blinds_exact_eight_columns(tmp_path):
    root = tmp_path / '.local'
    root.mkdir()
    rows = [{'item_id':str(i),'conversation_id':f'c{i}','subject':'当前用户',
             'candidate':f'虚构候选{i}', 'source':[{'source_id':'u','role':'user','text':'虚构原话'}]}
            for i in range(150)]
    def write(name, data):
        path = root / name
        path.write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in data))
        return path
    items = write('items.jsonl', rows)
    labels = write('labels.jsonl',[{'item_id':r['item_id'],'label':'keep','reason':'supported'} for r in rows])
    all_excluded = {str(i) for i in range(30)} | {'outside-pool'}
    projected = all_excluded & {r['item_id'] for r in rows}
    excluded = write('excluded.jsonl',[{'item_id':k,'label':'keep','reason':'owner-confirmed'} for k in projected])
    out = root / 'audit'
    report = prepare_joint_audit(items=items,left=labels,right=labels,prior_human=excluded,
                                 output=out,seed=20261025,sample_size=72)
    assert report['previous_review_overlap'] == 0 and report['sample'] == 72
    assert report['owner_rejected_removed'] == 0
    mapping = json.loads((out/'opaque-map-private.json').read_text())
    assert not (set(mapping.values()) & all_excluded)
    with (out/'audit-blind.csv').open(encoding='utf-8-sig',newline='') as f:
        reader = csv.DictReader(f)
        assert tuple(reader.fieldnames) == FIELDS
        public = list(reader)
    assert len(public) == 72
    assert all(not r['human_label'] and not r['human_reason'] for r in public)
    assert all(len(r['item_id']) == 32 and json.loads(r['source'])[0]['role'] == 'user' for r in public)


def test_partial_pair_cannot_generate_audit(monkeypatch, tmp_path):
    import importlib.util
    from types import SimpleNamespace

    spec = importlib.util.spec_from_file_location('complete_pool_test','scripts/complete-pool-refresh-v3.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    root = tmp_path / '.local'
    root.mkdir()
    (root/'pool-items.jsonl').write_text(json.dumps({'item_id':'i'})+'\n')
    monkeypatch.setattr(module,'ROOT',root)
    monkeypatch.setattr(module,'driver',lambda:SimpleNamespace(MODELS=('one','two'),verify=dict))
    monkeypatch.setattr(module,'checked',lambda model:{})
    with pytest.raises(ValueError,match='full paired coverage'):
        module.finalize()
    assert not (root/'audit72-final').exists()
