"""The new owner profile cannot leak back to exploratory models or Ark."""
import json

import pytest

from agent_memory.evals.b0_frozen import AUTH, request_allowed, validate


def test_recovery_only_accepts_identical_frozen_configuration(tmp_path):
    config = {**profile(), 'baseline_configuration_id': 'frozen-test', 'resume_roots': [],
              'role_accounts': {'embedding': {'TokenHub': 'tokenhub-secondary'}}}
    path = tmp_path / 'run-manifest.json'
    path.write_text(json.dumps({'config': config,
        'baseline_commit': '1e9d6f3b25b58c85792344000d7e1b5a71a79737'}))
    resumed = {**config, 'resume_roots': [str(tmp_path)]}
    validate(resumed)
    validate({**resumed, 'role_accounts': {'embedding': {'TokenHub': 'tokenhub-primary'}}})
    with pytest.raises(ValueError):
        validate({**resumed, 'role_accounts': {'embedding': {'TokenHub': 'unknown-key'}}})
    for change in ({'baseline_configuration_id': 'another'},
                   {'calibration_seed': 111}, {'embedding_call_budget': 101},
                   {'answer_models': ['deepseek-other']}, {'judge_models': ['minimax-m3']}):
        with pytest.raises(ValueError):
            validate({**resumed, **change})
    old = json.loads(path.read_text())
    old['config'].pop('frozen_b0_authorization')
    path.write_text(json.dumps(old))
    with pytest.raises(ValueError, match='FROZEN_OLD_TABLE_ADOPTION_FORBIDDEN'):
        validate(resumed)


def profile():
    return {'frozen_b0_authorization': AUTH, 'extraction_model': 'deepseek-v4-pro',
            'extraction_provider': 'DeepSeek', 'answer_models': ['deepseek-v4-pro'],
            'answer_provider': 'DeepSeek', 'embedding_provider': 'TokenHub',
            'embedding_model': 'kinfra-text-embedding-0.6b', 'embedding_protocol': 'openai',
            'embedding_call_budget': 100, 'judge_provider': 'TokenHub',
            'judge_models': ['glm-5.2', 'minimax-m3'],
            'cross_reference_model': 'mimo-v2.6-flash',
            'expected_response_models': {'extraction': 'deepseek-v4-pro'}}


def test_frozen_roles_and_no_ark_no_mixed_answers():
    config = profile()
    validate(config)
    assert request_allowed(config, 'answer', 'deepseek-v4-pro', 'DeepSeek')
    assert request_allowed(config, 'embedding', 'kinfra-text-embedding-0.6b', 'TokenHub')
    assert request_allowed(config, 'judge', 'glm-5.2', 'TokenHub')
    assert not request_allowed(config, 'answer', 'hy-mt2-pro', 'TokenHub')
    assert not request_allowed(config, 'answer', 'deepseek-flash', 'DeepSeek')
    assert not request_allowed(config, 'embedding', 'doubao-embedding-vision-251215', 'Ark')
    assert not request_allowed(config, 'tokenizer', 'deepseek-v4-pro', 'Ark')
    assert not request_allowed(config, 'judge', 'deepseek-v4-pro', 'DeepSeek')
    with pytest.raises(ValueError, match='ROLE_MISMATCH'):
        validate({**config, 'answer_models': ['deepseek-v4-pro', 'hy3']})
    with pytest.raises(ValueError, match='OLD_TABLE'):
        validate({**config, 'resume_roots': ['prior-mixed-table']})
    with pytest.raises(ValueError, match='ROTATION_FORBIDDEN'):
        validate({**config, 'four_key_authorization': 'old-authorization'})
