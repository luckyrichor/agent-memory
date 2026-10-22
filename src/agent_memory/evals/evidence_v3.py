"""Owner-approved evidence protocol: exact user-quote validation, no semantic proxy."""

import hashlib
import json
import random
from collections import Counter
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

MODELS = ("deepseek-v4-pro", "mimo-v2.6-flash")
DIMENSIONS = ("subject", "relation", "degree", "frequency", "quantity", "time", "diagnostic_certainty")
VERSION = "labeling-guide-v3-evidence-v1"


class Quote(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    detail: str
    source_id: str
    quote: str


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    subject: list[Quote]
    relation: list[Quote]
    degree: list[Quote]
    frequency: list[Quote]
    quantity: list[Quote]
    time: list[Quote]
    diagnostic_certainty: list[Quote]


class EvidenceLabel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    item_id: str
    label: Literal["keep", "discard", "uncertain"]
    reason: Literal["supported", "missing", "attribution", "temporary", "sensitive", "uncertain"]
    evidence: Evidence


class EvidenceBatch(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    labels: list[EvidenceLabel]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def validate_quotes(label: EvidenceLabel, item: dict[str, Any]) -> dict[str, Any]:
    """Only exact citation mechanics; does NOT prove entailment/detail completeness."""
    if label.item_id != item["item_id"]:
        raise ValueError("citation item identity mismatch")
    sources = {s["source_id"]: s for s in item["source"]}
    if len(sources) != len(item["source"]):
        raise ValueError("ambiguous duplicate source ID")
    failures = []
    references = 0
    for dimension in DIMENSIONS:
        for citation in getattr(label.evidence, dimension):
            references += 1
            source = sources.get(citation.source_id)
            if not citation.detail.strip() or not citation.quote.strip():
                failures.append("empty-citation")
            elif source is None:
                failures.append("unknown-source-id")
            elif source["role"] != "user":
                failures.append("not-user-source")
            elif citation.quote not in source["text"]:
                failures.append("quote-not-exact-substring")
    if label.label == "keep" and (not label.evidence.subject or not label.evidence.relation):
        failures.append("missing-subject-or-relation-evidence")
    return {
        "item_id": label.item_id,
        "label": "uncertain" if failures else label.label,
        "reason": "citation-invalid" if failures else label.reason,
        "model_label": label.label,
        "citation_valid": not failures,
        "citation_failures": sorted(set(failures)),
        "reference_count": references,
    }


def grouped_split(
    items: dict[str, dict[str, Any]], groups: dict[str, str], seed: int = 20261024
) -> dict[str, Any]:
    """Seeded conversation-disjoint, approximately half per known audit stratum.

    Labels are used ONLY to balance the split; never exposed in model inputs.
    Selection uses counts alone, not prompt outcomes. Manifest is frozen before calls.
    """
    if not groups or not groups.keys() <= items.keys():
        raise ValueError("invalid owner audit coverage")
    conversations = sorted({items[k]["conversation_id"] for k in groups})
    totals = Counter(groups.values())
    rng = random.Random(seed)
    best: tuple[float, list[str]] | None = None
    for _ in range(2000):
        shuffled = conversations.copy()
        rng.shuffle(shuffled)
        chosen = set(shuffled[: len(shuffled) // 2])
        dev = sorted(k for k in groups if items[k]["conversation_id"] in chosen)
        counts = Counter(groups[k] for k in dev)
        loss = abs(len(dev) - len(groups) / 2) + sum(
            abs(counts[g] - n / 2) for g, n in totals.items()
        )
        if best is None or loss < best[0]:
            best = loss, dev
    assert best is not None
    dev = best[1]
    final = sorted(groups.keys() - set(dev))
    return {
        "seed": seed,
        "unit": "conversation_id",
        "development": dev,
        "final": final,
        "development_strata": dict(Counter(groups[k] for k in dev)),
        "final_strata": dict(Counter(groups[k] for k in final)),
        "conversation_overlap": len(
            {items[k]["conversation_id"] for k in dev}
            & {items[k]["conversation_id"] for k in final}
        ),
        "historical_exposure": "All 229 owner answers existed before this protocol; previous filter used 72. New holdout is reserved for this prompt version, not a historically unseen benchmark.",
    }


def metrics(
    predictions: dict[str, dict[str, Any]], groups: dict[str, str], ids: list[str]
) -> dict[str, Any]:
    """Missing calls never become rejections or guessed scores."""
    result: dict[str, Any] = {}
    for group in sorted(set(groups.values())):
        wanted = [k for k in ids if groups[k] == group]
        seen = [k for k in wanted if k in predictions]
        good = sum(
            (predictions[k]["label"] == "keep") == group.endswith("keep") for k in seen
        )
        result[group] = {
            "expected": len(wanted),
            "observed": len(seen),
            "correct": good,
            "rate": good / len(wanted) if wanted and len(seen) == len(wanted) else None,
        }
    return result


def gate(scores: dict[str, Any]) -> bool:
    limits = {"blind72-discard": 8 / 9, "blind72-keep": 0.6, "native157-keep": 0.6}
    return all(
        scores[k]["expected"] > 0
        and scores[k]["rate"] is not None
        and scores[k]["rate"] >= threshold
        for k, threshold in limits.items()
    )
