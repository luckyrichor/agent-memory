import pytest

from agent_memory.evals.b0 import (
    calibration_sample,
    cosine_rank,
    development_ids,
    sample_development,
)


def test_dev_isolation_and_stable_sampling():
    rows = [{'conversation_id': str(i), 'answer': 'private'} for i in range(8)]
    split = {'dev': ['0', '2', '4', '6'], 'test': ['1', '3', '5', '7']}
    selected = sample_development(rows, split, 2)
    assert selected == sample_development(rows, split, 2)
    assert len(selected) == 2
    assert {r['conversation_id'] for r in selected} <= set(split['dev'])
    with pytest.raises(ValueError):
        development_ids({'dev': ['0'], 'test': ['0']})


def test_exact_vector_baseline_uses_cosine_not_length_or_gold():
    assert cosine_rank([1, 0], [[0, 9], [2, 0], [-1, 0], [1, 1]], 4) == [1, 3, 0, 2]
    with pytest.raises(ValueError):
        cosine_rank([0, 0], [[1, 0]], 1)
    with pytest.raises(ValueError):
        cosine_rank([1, 0], [[1]], 1)


def test_calibration_covers_errors_and_groups_and_is_reproducible():
    rows = [{'row_id': str(i), 'category': str(i % 3), 'system': str(i % 4),
             'judge_correct': i % 7 != 0} for i in range(600)]
    chosen = calibration_sample(rows)
    assert len(chosen) == len({r['row_id'] for r in chosen}) == 300
    assert chosen == calibration_sample(rows)
    strata = lambda rs: {(r['category'], r['system'], r['judge_correct']) for r in rs}
    assert strata(chosen) == strata(rows)
    with pytest.raises(ValueError):
        calibration_sample(rows[:20])


def test_paired_difference_preserves_clusters_signed_changes_and_coverage():
    from agent_memory.evals.b0 import clustered_paired

    before = {('a', 'q1', 0): True, ('a', 'q1', 1): True, ('b', 'q2', 0): False}
    after = {('a', 'q1', 0): False, ('a', 'q1', 1): True, ('b', 'q2', 0): True}
    result = clustered_paired(before, after)
    assert result['delta'] == 0
    assert result['paired_rows'] == 3
    assert result['conversation_clusters'] == 2
    assert result['improved_rows'] == result['worsened_rows'] == 1
    assert result['ci95'][0] <= 0 <= result['ci95'][1]
    with pytest.raises(ValueError):
        clustered_paired(before, {})


def test_external_vector_corpus_keeps_policy_rejected_source_and_all_chunks():
    from agent_memory.evals.b0 import chunk_source_documents

    original = [{'source_id': 'long', 'text': '中' * 4001, 'role': 'source'},
                {'source_id': 'policy-rejected', 'text': 'alice@example.test', 'role': 'user'}]
    chunks = chunk_source_documents(original)
    assert len(chunks) == 3
    assert ''.join(r['text'] for r in chunks if r['source_id'] == 'long') == '中' * 4001
    assert chunks[-1]['text'] == original[-1]['text']
    assert {r['source_id'] for r in chunks} == {'long', 'policy-rejected'}


def test_checkpoint_requires_complete_unique_rows_and_frozen_measurement_config():
    from agent_memory.evals.b0 import complete_checkpoint, measurement_signature

    assert complete_checkpoint([{'row_id': 'one'}, {'row_id': 'two'}], {'one', 'two'})
    assert not complete_checkpoint([{'row_id': 'one'}], {'one', 'two'})
    assert not complete_checkpoint([{'row_id': 'one'}, {'row_id': 'one'}], {'one'})
    original = {'seed': 42, 'extraction_model': 'frozen', 'embedding_cache_roots': ['old']}
    assert measurement_signature(original) == measurement_signature({
        **original, 'embedding_cache_roots': ['new'], 'resume_roots': ['verified']})
    assert measurement_signature(original) != measurement_signature({
        **original, 'extraction_model': 'changed'})
    assert measurement_signature({**original, 'answer_provider': 'Ark'}) != measurement_signature({
        **original, 'answer_provider': 'TokenHub'})


def test_rotation_tries_other_key_and_preserves_vendor_gates():
    from agent_memory.evals.b0_rotation import candidates, quota

    options = candidates('extraction', 'doubao-seed-2-1-lite-260915', 'Ark',
                         {'TokenHub': ['mimo-v2.6-flash']},
                         {('ark-secondary', 'doubao-seed-2-1-lite-260915')},
                         answer_vendor='ByteDance', judge_vendor='Zhipu')
    assert options[0] == ('Ark', 'ark-primary', 'doubao-seed-2-1-lite-260915')
    assert ('TokenHub', 'tokenhub-primary', 'mimo-v2.6-flash') in options
    judges = candidates('judge', 'glm-5.2', 'TokenHub',
                        {'TokenHub': ['hy4-preview', 'deepseek-v4.1-flash-1017',
                                      'mimo-v2.6-flash', 'minimax-m3']}, set(),
                        answer_vendor='Xiaomi', judge_vendor='Zhipu')
    assert all(model == 'glm-5.2' for _, _, model in judges)
    assert quota({'http': 429, 'error_code': 'SetLimitExceeded'})
    assert not quota({'http': 429, 'error_code': 'RateLimitExceeded'})


def test_overdue_is_quota_but_generic_forbidden_is_not():
    from agent_memory.evals.b0_rotation import quota

    assert quota({'http': 403, 'error_code': 'AccountOverdueError'})
    assert not quota({'http': 403, 'error_code': 'AccessDenied'})


def test_embedding_float_variation_does_not_inherit_judge_label_gate():
    from agent_memory.evals.b0 import embedding_probe_observations, normalize_embedding_request

    vectors = [[1.0, i * .00001] + [0.0] * 1022 for i in range(106)]
    result = embedding_probe_observations(vectors)
    assert result['passed'] and not result['exact_repeat_equality_diagnostic']
    assert result['format_valid'] == 100 and not result['exact_vector_equality_is_gate']
    invalid = [v[:] for v in vectors]
    invalid[0][0] = float('nan')
    assert not embedding_probe_observations(invalid)['passed']
    assert not embedding_probe_observations(vectors[:105])['passed']
    body = {'model': 'kinfra-text-embedding-0.6b', 'input': 'fictional', 'dimensions': 1024}
    assert 'dimensions' not in normalize_embedding_request(body, 'TokenHub')
    assert normalize_embedding_request(body, 'Ark')['dimensions'] == 1024
    assert body['dimensions'] == 1024


def test_direct_deepseek_is_last_and_cannot_judge_own_annotation():
    from agent_memory.evals.b0_rotation import candidates

    catalog = {'TokenHub': ['hy3'], 'Ark': ['doubao-seed-2-1-lite-260915'],
               'DeepSeek': ['deepseek-flash']}
    choices = candidates('answer', 'deepseek-flash', 'DeepSeek', catalog, set(),
                         answer_vendor='DeepSeek', judge_vendor='Zhipu')
    assert choices and choices[-1][0] == 'DeepSeek'
    first_direct = next(i for i, c in enumerate(choices) if c[0] == 'DeepSeek')
    assert all(c[0] != 'DeepSeek' for c in choices[:first_direct])
    judges = candidates('judge', 'glm-5.2', 'TokenHub', catalog, set(),
                        answer_vendor='Tencent', judge_vendor='Zhipu')
    assert all(c[0] != 'DeepSeek' for c in judges)
