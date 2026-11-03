"""Owner-frozen B0 rebuild policy: one DeepSeek version, Tencent vectors, no Ark."""
import json
from pathlib import Path
from typing import Any

AUTH = 'om_x100b62c56df1b8b0ce44568e5c1acc0'
BIAS = ('DeepSeek 同时是金标准标注模型之一，答题与抽取模型与标注模型同厂商，'
        '可能使抽取类指标略偏高；金标准要求两个厂商模型共同保留，已部分抵消这一影响。')


def is_frozen(config: dict[str, Any]) -> bool:
    return config.get('frozen_b0_authorization') == AUTH


def recovery_identity(config: dict[str, Any]) -> dict[str, Any]:
    """Credential slots are interchangeable only for the same fixed TokenHub models."""
    result = {k: v for k, v in config.items() if k not in {'resume_roots', 'role_accounts'}}
    accounts = config.get('role_accounts', {})
    result['role_accounts'] = {
        role: {provider: ('authorized-tokenhub-slot' if provider == 'TokenHub'
                and alias in {'tokenhub-primary', 'tokenhub-secondary'} else alias)
               for provider, alias in providers.items()}
        for role, providers in accounts.items()
    }
    return result


def validate(config: dict[str, Any]) -> None:
    if not is_frozen(config):
        return
    model = config.get('extraction_model', '')
    if (not model.startswith('deepseek-') or config.get('answer_models') != [model]
            or config.get('extraction_provider') != 'DeepSeek'
            or config.get('answer_provider') != 'DeepSeek'):
        raise ValueError('FROZEN_DEEPSEEK_ROLE_MISMATCH')
    if (config.get('embedding_provider') != 'TokenHub'
            or config.get('embedding_model') != 'kinfra-text-embedding-0.6b'
            or config.get('embedding_protocol') != 'openai'):
        raise ValueError('FROZEN_TENCENT_VECTOR_REQUIRED')
    if not isinstance(config.get('embedding_call_budget'), int) or config['embedding_call_budget'] <= 0:
        raise ValueError('FROZEN_VECTOR_BUDGET_REQUIRED')
    from agent_memory.evals.b0_rotation import vendor

    if (config.get('judge_provider') != 'TokenHub' or not config.get('judge_models')
            or any(vendor(m) not in {'Zhipu', 'Xiaomi', 'MiniMax'}
                   for m in config.get('judge_models', []))):
        raise ValueError('FROZEN_JUDGE_POOL_REQUIRED')
    if config.get('family_continuation_authorization') or config.get('four_key_authorization'):
        raise ValueError('FROZEN_AUTOMATIC_MODEL_ROTATION_FORBIDDEN')
    for root in config.get('resume_roots', []):
        try:
            prior = json.loads((Path(root) / 'run-manifest.json').read_text())
            previous = prior['config']
            if (not is_frozen(previous) or not config.get('baseline_configuration_id')
                    or prior.get('baseline_commit') != '1e9d6f3b25b58c85792344000d7e1b5a71a79737'
                    or recovery_identity(previous) != recovery_identity(config)):
                raise ValueError('different frozen configuration')
        except (OSError, KeyError, ValueError) as exc:
            raise ValueError('FROZEN_OLD_TABLE_ADOPTION_FORBIDDEN') from exc
    if not config.get('expected_response_models', {}).get('extraction'):
        raise ValueError('FROZEN_OBSERVED_VERSION_REQUIRED')


def request_allowed(config: dict[str, Any], role: str, model: str, provider: str) -> bool:
    if not is_frozen(config):
        return True
    if role in ('answer', 'extraction'):
        return provider == 'DeepSeek' and model == config['extraction_model']
    if role == 'embedding':
        return provider == 'TokenHub' and model == config['embedding_model']
    if role == 'judge':
        return provider == 'TokenHub' and model in config['judge_models']
    if role == 'cross-reference':
        return provider == 'TokenHub' and model == config.get('cross_reference_model')
    return False  # In particular, do not send target tokenization requests to Ark.
