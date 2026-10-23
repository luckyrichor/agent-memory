"""Measurement helpers: strict dev isolation and an honest single-channel baseline."""

import math
import random
from collections import defaultdict
from collections.abc import Sequence
from typing import Any


def development_ids(split: dict[str, list[str]]) -> set[str]:
    dev, test = split["dev"], split["test"]
    if len(dev) != len(set(dev)) or len(test) != len(set(test)) or set(dev) & set(test):
        raise ValueError("invalid frozen conversation split")
    return set(dev)


def sample_development(
    rows: Sequence[dict[str, Any]], split: dict[str, list[str]], limit: int, *, seed: int = 42
) -> list[dict[str, Any]]:
    allowed = development_ids(split)
    candidates = [row for row in rows if row["conversation_id"] in allowed]
    if len({row["conversation_id"] for row in candidates}) != len(candidates):
        raise ValueError("duplicate source conversation")
    if limit < 0:
        raise ValueError("negative sample size")
    selected = set(random.Random(seed).sample(sorted(r["conversation_id"] for r in candidates),
                                             min(limit, len(candidates))))
    return [row for row in candidates if row["conversation_id"] in selected]


def cosine_rank(query: Sequence[float], vectors: Sequence[Sequence[float]], k: int) -> list[int]:
    """Exact full-scan cosine; no filters, lexical scores, fusion, or gold answers."""
    if k < 1 or not query or not all(math.isfinite(x) for x in query):
        raise ValueError("invalid query or k")
    qnorm = math.sqrt(sum(x*x for x in query))
    if not qnorm:
        raise ValueError("zero query vector")
    scores = []
    for i, vector in enumerate(vectors):
        if len(vector) != len(query) or not all(math.isfinite(x) for x in vector):
            raise ValueError("incompatible embedding")
        norm = math.sqrt(sum(x*x for x in vector))
        if not norm:
            raise ValueError("zero document vector")
        scores.append((sum(x*y for x, y in zip(query, vector, strict=True))/(qnorm*norm), i))
    return [i for _, i in sorted(scores, key=lambda p: (-p[0], p[1]))[:k]]


def calibration_sample(
    rows: Sequence[dict[str, Any]], count: int = 300, *, seed: int = 42
) -> list[dict[str, Any]]:
    """Allocate across type/system/judge-correctness strata, no grades in export."""
    if count < 1 or len({r['row_id'] for r in rows}) != len(rows):
        raise ValueError("invalid calibration population")
    valid = [r for r in rows if type(r.get('judge_correct')) is bool]
    if len(valid) < count:
        raise ValueError("insufficient valid rows for owner calibration")
    strata: dict[tuple[str, str, bool], list[dict[str, Any]]] = defaultdict(list)
    for row in valid:
        strata[(row['category'], row['system'], row['judge_correct'])].append(row)
    if len(strata) > count:
        raise ValueError("requested calibration size cannot cover all observed strata")
    rng = random.Random(seed)
    for values in strata.values():
        values.sort(key=lambda r: r['row_id'])
        rng.shuffle(values)
    chosen: list[dict[str, Any]] = []
    keys = sorted(strata)
    while len(chosen) < count:
        for key in keys:
            if strata[key] and len(chosen) < count:
                chosen.append(strata[key].pop())
    rng.shuffle(chosen)
    return chosen


def clustered_paired(
    before: dict[tuple[str, str, int], bool],
    after: dict[tuple[str, str, int], bool],
) -> dict[str, Any]:
    """Paired accuracy change, resampling conversations including all repeats.

    An affine shift keeps ratio's nonnegative count representation; subtracting
    one from its result gives exactly the original signed mean difference.
    """
    from agent_memory.evals.metrics import ratio

    if not before or before.keys() != after.keys():
        raise ValueError("paired comparison needs identical valid question/repeat coverage")
    clusters: dict[str, list[int]] = defaultdict(list)
    for key in sorted(before):
        clusters[key[0]].append(int(after[key]) - int(before[key]))
    shifted = ratio([(float(sum(ds) + len(ds)), float(len(ds))) for ds in clusters.values()])
    assert shifted.value is not None and shifted.ci95 is not None
    return {
        "delta": shifted.value - 1,
        "ci95": [bound - 1 for bound in shifted.ci95],
        "conversation_clusters": shifted.n,
        "paired_rows": len(before),
        "improved_rows": sum(not before[k] and after[k] for k in before),
        "worsened_rows": sum(before[k] and not after[k] for k in before),
        "method": "paired conversation-cluster ratio-of-sums bootstrap1000 seed42",
    }


def chunk_source_documents(documents: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """All raw-source chunks for the external baseline, independent of SUT admission."""
    chunks: list[dict[str, Any]] = []
    for document in documents:
        if not isinstance(document.get("text"), str):
            raise TypeError("source text required")
        for start in range(0, len(document["text"]), 4000):
            chunks.append({**document, "text": document["text"][start:start + 4000],
                           "part": start // 4000})
    return chunks


def measurement_signature(config: dict[str, Any]) -> dict[str, Any]:
    """Only non-measurement recovery metadata may differ across checkpoints."""
    keys = ('seed', 'conversations_per_dataset', 'conversations_per_question_type',
            'questions_per_conversation', 'system_context_budget', 'offline_fixture')
    result = {key: config.get(key) for key in keys}
    result.update(extraction_model=config.get('extraction_model', 'doubao-seed-2-1-pro-260915'),
                  extraction_provider=config.get('extraction_provider', 'Ark'),
                  embedding_model=config.get('embedding_model', 'doubao-embedding-vision-251215'),
                  embedding_provider=config.get('embedding_provider', 'Ark'),
                  embedding_protocol=config.get('embedding_protocol', 'ark'),
                  answer_model=config.get('answer_models', ['doubao-seed-2-1-pro-260915'])[0],
                  answer_provider=config.get('answer_provider', 'Ark' if config.get(
                      'answer_models', ['doubao-seed-2-1-pro-260915'])[0].startswith('doubao') else 'TokenHub'),
                  judge_model=config.get('judge_model', 'glm-5.2'),
                  judge_provider=config.get('judge_provider', 'TokenHub'))
    return result



def complete_checkpoint(rows: Sequence[dict[str, Any]], expected_ids: set[str]) -> bool:
    ids = [row['row_id'] for row in rows]
    return len(ids) == len(set(ids)) and set(ids) == expected_ids


FAMILY_CONTINUATION_AUTH = "om_x100b628d31ba14a0df2cc7d1869eac1"


def compatible_measurement(previous: dict[str, Any], current: dict[str, Any]) -> bool:
    """Owner-authorized family mixtures; embedding space remains exact, never family-only."""
    from agent_memory.evals.b0_rotation import vendor

    before, after = measurement_signature(previous), measurement_signature(current)
    if before == after:
        return True
    if current.get('family_continuation_authorization') != FAMILY_CONTINUATION_AUTH:
        return False
    for role in ('extraction', 'answer', 'judge'):
        old, new = str(before[role + '_model']), str(after[role + '_model'])
        if not vendor(old) or vendor(old) != vendor(new):
            return False
        before.pop(role + '_model')
        after.pop(role + '_model')
        before.pop(role + '_provider')
        after.pop(role + '_provider')
    return before == after


def compatible_result_model(actual: str | None, configured: str, config: dict[str, Any]) -> bool:
    from agent_memory.evals.b0_rotation import vendor

    return actual == configured or (
        config.get('family_continuation_authorization') == FAMILY_CONTINUATION_AUTH
        and vendor(configured) is not None and actual is not None
        and vendor(actual) == vendor(configured))
