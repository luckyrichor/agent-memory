"""Finite role-aware failover policy; credentials and HTTP live outside this module."""
import re
from typing import Any

ACCOUNTS = {'Ark': ('ark-primary', 'ark-secondary'),
            'TokenHub': ('tokenhub-primary', 'tokenhub-secondary')}


def vendor(model: str) -> str | None:
    families = {'doubao': 'ByteDance', 'glm': 'Zhipu', 'mimo': 'Xiaomi',
                'minimax': 'MiniMax', 'deepseek': 'DeepSeek', 'hunyuan': 'Tencent',
                'hy': 'Tencent', 'qwen': 'Alibaba', 'ernie': 'Baidu',
                'gpt': 'OpenAI', 'claude': 'Anthropic', 'gemini': 'Google', 'llama': 'Meta'}
    return next((name for prefix, name in families.items() if model.lower().startswith(prefix)), None)


def quota(record: dict[str, Any]) -> bool:
    return record.get('http') == 402 or record.get('error_code') in (
        'SetLimitExceeded', '401010', 'QuotaExceeded', 'InsufficientBalance', 'AccountOverdueError')


def candidates(role: str, model: str, provider: str, catalog: dict[str, list[str]],
               unavailable: set[tuple[str, str]], *, answer_vendor: str | None,
               judge_vendor: str | None) -> list[tuple[str, str, str]]:
    """Same model on another key first; only applicable catalog models follow."""
    ordered = [(provider, account, model) for account in ACCOUNTS[provider]]
    preference = ('doubao-seed-2-1-pro-260915', 'doubao-seed-2-1-lite-260915',
                  'mimo-v2.6-flash', 'minimax-m3', 'deepseek-v4.1-flash-1017',
                  'glm-5.2', 'hy4-preview', 'hunyuan-role-latest')
    if role != 'cross-reference':
        providers = (provider, *[p for p in ACCOUNTS if p != provider])
        models = [(p, m) for p in providers for m in set(catalog.get(p, []))]
        models.sort(key=lambda item: (preference.index(item[1]) if item[1] in preference else 999,
                                      providers.index(item[0]), item[1]))
        for candidate_provider, candidate in models:
            for account in ACCOUNTS[candidate_provider]:
                ordered.append((candidate_provider, account, candidate))
    seen: set[tuple[str, str, str]] = set()
    result = []
    for candidate_provider, account, candidate in ordered:
        item = (candidate_provider, account, candidate)
        if item in seen or (account, candidate) in unavailable:
            continue
        seen.add(item)
        embedding = 'embedding' in candidate.lower()
        if role == 'embedding':
            if not embedding:
                continue
        elif embedding or re.search('seedance|seedream|seed3d|translation|whisper|tts|asr|kimi', candidate.lower()) or vendor(candidate) is None:
            continue
        if role == 'judge' and vendor(candidate) in {answer_vendor, 'DeepSeek', 'Tencent', 'MiniMax'}:
            continue
        if role in ('answer', 'extraction') and vendor(candidate) == judge_vendor:
            continue
        result.append(item)
    return result
