"""Auditable formulas. Undefined denominators stay undefined; no missing value is a zero."""

import math
import random
from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from statistics import fmean


@dataclass(frozen=True)
class Estimate:
    value: float | None
    n: int
    numerator: float
    denominator: float
    ci95: tuple[float, float] | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def quantile(values: Sequence[float], p: float) -> float | None:
    """Linear interpolation, (n-1)*p; caller reports the convention and sample count."""
    if not 0 <= p <= 1:
        raise ValueError("quantile outside [0,1]")
    if any(not math.isfinite(x) for x in values):
        raise ValueError("nonfinite measurement")
    if not values:
        return None
    ordered = sorted(values)
    pos = (len(ordered) - 1) * p
    lo = math.floor(pos)
    hi = math.ceil(pos)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


def ratio(observations: Sequence[tuple[float, float]], *, seed: int = 42) -> Estimate:
    """Ratio of sums; 1000 paired bootstrap resamples of observation units.

    For clustered data the observation unit MUST be a conversation, aggregated
    before calling. Can represent counts/tokens too, so numerator need not <= denominator.
    """
    if any(not math.isfinite(v) or v < 0 for pair in observations for v in pair):
        raise ValueError("invalid nonnegative observation")
    numerator = sum(a for a, _ in observations)
    denominator = sum(b for _, b in observations)
    if not denominator:
        return Estimate(None, len(observations), numerator, denominator, None)
    rng = random.Random(seed)
    boot = []
    for _ in range(1000):
        sample = rng.choices(observations, k=len(observations))
        den = sum(b for _, b in sample)
        if den:
            boot.append(sum(a for a, _ in sample) / den)
    low, high = quantile(boot, 0.025), quantile(boot, 0.975)
    ci = (low, high) if low is not None and high is not None else None
    return Estimate(numerator / denominator, len(observations), numerator, denominator, ci)


def clopper_pearson(
    successes: int, trials: int, *, confidence: float = 0.95
) -> tuple[float, float] | None:
    """Equal-tailed exact binomial interval, supplementary to cluster bootstrap.

    Assumes independent Bernoulli trials: this does not adjust for conversation
    clustering or sampling without replacement. Invert binomial tails directly;
    edge cases use their closed forms, not a degenerate resampling interval.
    """
    if not 0 <= successes <= trials or not math.isfinite(confidence) or not 0 < confidence < 1:
        raise ValueError("invalid binomial counts or confidence")
    if trials == 0:
        return None
    tail = (1 - confidence) / 2
    if successes == trials:
        return tail ** (1 / trials), 1.0
    if successes == 0:
        return 0.0, 1 - tail ** (1 / trials)

    def probability(p: float, start: int, end: int) -> float:
        if p == 0:
            return float(start == 0)
        if p == 1:
            return float(end == trials)
        return math.fsum(
            math.exp(
                math.lgamma(trials + 1)
                - math.lgamma(k + 1)
                - math.lgamma(trials - k + 1)
                + k * math.log(p)
                + (trials - k) * math.log1p(-p)
            )
            for k in range(start, end + 1)
        )

    lo, hi = 0.0, 1.0
    for _ in range(80):
        mid = (lo + hi) / 2
        if probability(mid, successes, trials) < tail:
            lo = mid
        else:
            hi = mid
    lower = (lo + hi) / 2
    lo, hi = 0.0, 1.0
    for _ in range(80):
        mid = (lo + hi) / 2
        if probability(mid, 0, successes) > tail:
            lo = mid
        else:
            hi = mid
    return lower, (lo + hi) / 2


def f1(precision: float | None, recall: float | None) -> float | None:
    if precision is None or recall is None:
        return None
    if not 0 <= precision <= 1 or not 0 <= recall <= 1:
        raise ValueError("invalid precision/recall")
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0


def retrieval(ranked: Sequence[str], relevance: dict[str, int], k: int) -> dict[str, float | None]:
    """One query: query hit vs evidence coverage are intentionally separate.

    Missing results occupy empty slots in Precision@k. nDCG uses 2**grade-1.
    Unanswerable queries have undefined recall/MRR/nDCG; RT6 measures them separately.
    """
    if k < 1 or len(set(ranked)) != len(ranked) or any(g < 0 for g in relevance.values()):
        raise ValueError("invalid ranking, grade or k")
    positive = {key for key, grade in relevance.items() if grade > 0}
    top = ranked[:k]
    hits = sum(key in positive for key in top)
    rr = next((1 / i for i, key in enumerate(ranked, 1) if key in positive), 0.0)
    dcg = sum((2 ** relevance.get(key, 0) - 1) / math.log2(i + 1) for i, key in enumerate(top, 1))
    ideal = sum(
        (2**grade - 1) / math.log2(i + 1)
        for i, grade in enumerate(sorted(relevance.values(), reverse=True)[:k], 1)
    )
    return {
        "RT1": float(hits > 0) if positive else None,
        "evidence_coverage": hits / len(positive) if positive else None,
        "RT2": hits / k,
        "RT3": rr if positive else None,
        "RT4": dcg / ideal if ideal else None,
    }


def latency(values: Sequence[float]) -> dict[str, int | float | None]:
    if any(v < 0 for v in values):
        raise ValueError("negative latency")
    return {
        "n": len(values),
        "p50": quantile(values, 0.5),
        "p95": quantile(values, 0.95),
        "p99": quantile(values, 0.99),
    }


def agreement(left: Sequence[str], right: Sequence[str]) -> dict[str, object]:
    if len(left) != len(right):
        raise ValueError("unpaired labels")
    matrix = Counter(zip(left, right, strict=True))
    if not left:
        return {"n": 0, "agreement": None, "kappa": None, "matrix": []}
    a, b = Counter(left), Counter(right)
    observed = sum(x == y for x, y in zip(left, right, strict=True)) / len(left)
    expected = sum(a[c] * b[c] for c in a.keys() | b.keys()) / len(left) ** 2
    return {
        "n": len(left),
        "agreement": observed,
        "kappa": (observed - expected) / (1 - expected) if expected < 1 else None,
        "matrix": [{"left": x, "right": y, "n": n} for (x, y), n in sorted(matrix.items())],
    }


def paired_difference(
    before: dict[str, float], after: dict[str, float], *, seed: int = 42
) -> dict[str, object]:
    if not before or before.keys() != after.keys():
        raise ValueError("paired comparison requires identical nonempty question IDs")
    keys = sorted(before)
    deltas = [after[key] - before[key] for key in keys]
    if any(not math.isfinite(v) for v in deltas):
        raise ValueError("nonfinite score")
    rng = random.Random(seed)
    boot = [fmean(rng.choices(deltas, k=len(deltas))) for _ in range(1000)]
    low, high = quantile(boot, 0.025), quantile(boot, 0.975)
    return {
        "n": len(keys),
        "delta": fmean(deltas),
        "ci95": [low, high],
        "excludes_zero": low is not None and high is not None and (low > 0 or high < 0),
        "increased": [key for key in keys if after[key] > before[key]],
        "decreased": [key for key in keys if after[key] < before[key]],
    }


def evidence_retrieval(
    ranked_evidence_sets: Sequence[Sequence[str]],
    relevance: dict[str, int],
    k: int,
) -> dict[str, float | None]:
    """Memory-item hit/precision/MRR, with coverage over distinct gold sources.

    A merged memory can cite multiple sources. Multiple memories from the same
    source remain separate ranking slots. Source labels alone do not define graded
    relevance for every memory candidate, so memory nDCG is unavailable, not guessed.
    """
    if k < 1 or any(g < 0 for g in relevance.values()):
        raise ValueError("invalid k or relevance grade")
    positive = {source for source, grade in relevance.items() if grade > 0}
    matched = [bool(set(sources) & positive) for sources in ranked_evidence_sets]
    top_sources = {source for sources in ranked_evidence_sets[:k] for source in sources}
    hits = sum(matched[:k])
    first = next((1 / i for i, hit in enumerate(matched, 1) if hit), 0.0)
    return {
        "RT1": float(hits > 0) if positive else None,
        "RT2": hits / k,
        "RT3": first if positive else None,
        "RT4": None,
        "evidence_coverage": len(top_sources & positive) / len(positive) if positive else None,
    }
