"""Independent raw-turn keyword baseline and source mapping audits, without answers."""

import math
import re
from collections import Counter
from typing import Any

from agent_memory.evals.datasets import Conversation

# Fixed generic English function words; no benchmark questions/answers used to tune this list.
STOPWORDS = frozenset(
    ["a", "an", "the", "and", "or", "but", "if", "as", "at", "by", "for", "from", "in", "into", "of", "on", "to", "with", "is", "are", "was", "were", "be", "been", "being", "do", "does", "did", "have", "has", "had", "can", "could", "would", "should", "will", "may", "might", "must", "what", "which", "who", "whom", "whose", "when", "where", "why", "how", "that", "this", "these", "those", "it", "its", "he", "she", "his", "her", "they", "their", "them", "we", "our", "you", "your", "i", "me", "my", "not", "than", "then", "there", "here", "about", "during", "after", "before"]
)


def keywords(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in STOPWORDS]


def keyword_predictions(conv: Conversation, k: int = 10) -> list[dict[str, Any]]:
    """BM25 over each original conversation turn, tie break in source order."""
    counts = [Counter(keywords(d.text)) for d in conv.documents]
    df: Counter[str] = Counter()
    for count in counts:
        df.update(count.keys())
    lengths = [sum(c.values()) for c in counts]
    avg = sum(lengths) / max(1, len(lengths)) or 1
    predictions = []
    for q in conv.questions:
        scores = []
        for index, (count, length) in enumerate(zip(counts, lengths, strict=True)):
            score = 0.0
            for term in set(keywords(q.text)):
                freq = count[term]
                if freq:
                    idf = math.log(1 + (len(counts) - df[term] + 0.5) / (df[term] + 0.5))
                    score += idf * freq * 2.2 / (freq + 1.2 * (0.25 + 0.75 * length / avg))
            if score > 0:
                scores.append((-score, index))
        selected = [conv.documents[i] for _, i in sorted(scores)[:k]]
        ids = [
            d.session_id if conv.metadata.get("evidence_level") == "session" else d.source_id
            for d in selected
        ]
        predictions.append(
            {
                "question_id": q.question_id,
                "ranked_source_ids": list(dict.fromkeys(ids)),
                "ranked_evidence_sets": [[s] for s in ids],
                "memory_results": len(ids),
                "unmapped_hits": 0,
            }
        )
    return predictions


def audit_mapping(conv: Conversation, mapping: list[dict[str, Any]]) -> dict[str, Any]:
    sources = {d.source_id for d in conv.documents}
    actual = {r["source_id"] for r in mapping}
    relevant = {s for q in conv.questions for s in q.relevant}
    expected = {
        (d.source_id, p) for d in conv.documents for p in range((len(d.text) + 3999) // 4000)
    }
    pairs = [(r["source_id"], r["part"]) for r in mapping]
    return {
        "source_documents": len(conv.documents),
        "unique_source_ids": len(sources),
        "mapped_chunks": len(mapping),
        "expected_chunks": len(expected),
        "missing_source_ids": len(sources - actual),
        "unexpected_source_ids": len(actual - sources),
        "missing_evidence_ids": len(relevant - sources),
        "chunk_mapping_bijective": len(pairs) == len(set(pairs)) and set(pairs) == expected,
        "unique_version_ids": len({r["version_id"] for r in mapping}),
        "questions": len(conv.questions),
        "positive_queries": sum(
            not q.abstention and bool(q.relevant) and q.evidence_available for q in conv.questions
        ),
        "abstentions": sum(q.abstention for q in conv.questions),
        "unavailable_evidence_queries": sum(not q.evidence_available for q in conv.questions),
    }
