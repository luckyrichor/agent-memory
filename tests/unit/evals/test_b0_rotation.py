"""Quota continuation must not mix model profiles or restart an owner calibration pause."""
import copy
import json
from pathlib import Path


def test_controller_key_change_model_change_and_owner_pause(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / 'scripts'))
    from b0_autorotate import Rotation, save

    profile = {
        'seed': 42, 'conversations_per_dataset': {'toy': 1},
        'questions_per_conversation': 1, 'system_context_budget': 2000,
        'extraction_model': 'doubao-seed-2-1-lite-260915', 'extraction_provider': 'Ark',
        'answer_models': ['doubao-seed-2-1-lite-260915'], 'judge_model': 'glm-5.2',
        'role_accounts': {'extraction': {'Ark': 'ark-secondary'},
                          'answer': {'Ark': 'ark-secondary'}},
        'four_key_authorization': 'om_x100b6280467a68a4c3cc0005fe78816',
    }
    original = copy.deepcopy(profile)
    run = tmp_path / 'run'
    run.mkdir()
    event = {'role': 'extraction', 'provider': 'Ark',
             'model': 'doubao-seed-2-1-lite-260915', 'account': 'ark-secondary',
             'http': 429, 'error_code': 'SetLimitExceeded'}
    save(run / 'runtime-quota-pause.json', event)
    rotation = Rotation(tmp_path / 'rotation', profile)
    monkeypatch.setattr(rotation, 'models', lambda: {'Ark': ['doubao-seed-2-1-pro-260915']})
    monkeypatch.setattr(rotation, 'qualify', lambda *_: True)
    updated = rotation.next(profile, run, [run], {'status': 'runtime_quota_paused'})
    assert updated['role_accounts']['extraction']['Ark'] == 'ark-primary'
    assert updated['role_accounts']['answer']['Ark'] == 'ark-primary'
    assert updated['resume_roots'] == [str(run)]
    assert profile == original
    rotation.unavailable.add(('ark-primary', event['model']))
    changed = rotation.next(profile, run, [run], {'status': 'runtime_quota_paused'})
    assert changed['extraction_model'] == 'doubao-seed-2-1-pro-260915'
    assert changed['answer_models'] == ['doubao-seed-2-1-pro-260915']
    assert changed['resume_roots'] == []
    assert rotation.next(profile, run, [run], {'status': 'paused_for_owner_calibration'}) is None
    assert json.loads((run / 'runtime-quota-pause.json').read_text()) == event

    vector_event = {**event, 'role': 'embedding', 'model': 'doubao-embedding-vision-251215'}
    save(run / 'runtime-quota-pause.json', vector_event)
    rotation.unavailable.add(('ark-primary', vector_event['model']))
    monkeypatch.setattr(rotation, 'models', lambda: {'TokenHub': ['kinfra-text-embedding-0.6b']})
    changed_space = rotation.next(profile, run, [run], {'status': 'runtime_quota_paused'})
    assert changed_space['embedding_provider'] == 'TokenHub'
    assert changed_space['embedding_protocol'] == 'openai'
    assert changed_space['resume_roots'] == [] and changed_space['embedding_cache_roots'] == []


def test_family_continuation_is_authorized_and_vector_space_stays_exact():
    from agent_memory.evals.b0 import (
        FAMILY_CONTINUATION_AUTH,
        compatible_measurement,
        compatible_result_model,
    )

    original = {'extraction_model': 'hy4-preview', 'answer_models': ['hy4-preview']}
    changed = {**original, 'extraction_model': 'hunyuan-role-latest',
               'answer_models': ['hunyuan-role-latest']}
    assert not compatible_measurement(original, changed)
    changed['family_continuation_authorization'] = FAMILY_CONTINUATION_AUTH
    assert compatible_measurement(original, changed)
    assert compatible_result_model('hy4-preview', 'hunyuan-role-latest', changed)
    assert not compatible_result_model('deepseek-v4.1-flash-1017', 'hunyuan-role-latest', changed)
    assert not compatible_measurement(original, {**changed, 'embedding_model': 'doubao-embedding-new'})
    assert not compatible_measurement(original, {**changed, 'embedding_provider': 'TokenHub'})
    assert not compatible_measurement(original, {**changed, 'seed': 99})
    assert not compatible_measurement(original, {**changed, 'judge_model': 'mimo-v2.6-flash'})


def test_controller_same_family_keeps_work_but_cross_family_restarts(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / 'scripts'))
    from b0_autorotate import Rotation, save

    from agent_memory.evals.b0 import FAMILY_CONTINUATION_AUTH

    profile = {'four_key_authorization': 'om_x100b6280467a68a4c3cc0005fe78816',
               'family_continuation_authorization': FAMILY_CONTINUATION_AUTH,
               'extraction_model': 'hy4-preview', 'extraction_provider': 'TokenHub',
               'answer_models': ['hy4-preview'], 'answer_provider': 'TokenHub',
               'judge_model': 'glm-5.2'}
    run = tmp_path / 'run'
    save(run / 'runtime-quota-pause.json', {'role': 'extraction', 'model': 'hy4-preview',
         'provider': 'TokenHub', 'account': 'tokenhub-secondary', 'http': 402})
    rotation = Rotation(tmp_path / 'rotation', profile)
    rotation.unavailable.add(('tokenhub-primary', 'hy4-preview'))
    monkeypatch.setattr(rotation, 'models', lambda: {
        'Ark': ['doubao-seed-2-1-pro-260915'], 'TokenHub': ['hunyuan-role-latest']})
    monkeypatch.setattr(rotation, 'qualify', lambda *_: True)
    updated = rotation.next(profile, run, [run], {'status': 'runtime_quota_paused'})
    assert updated['extraction_model'] == 'hunyuan-role-latest'
    assert updated['resume_roots'] == [str(run)]
    for account in ('tokenhub-primary', 'tokenhub-secondary'):
        rotation.unavailable.add((account, 'hunyuan-role-latest'))
    updated = rotation.next(profile, run, [run], {'status': 'runtime_quota_paused'})
    assert updated['extraction_model'].startswith('doubao') and updated['resume_roots'] == []
