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
