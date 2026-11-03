"""E4: rule-based conflict marking between memories that share one context packet.

**This does not judge meaning.** No model is called, and no claim is made that two memories
actually disagree. The rule is structural: memories about the same subject, of the same type,
whose wording overlaps heavily while their text differs. That is the shape a corrected fact takes
("the rollout window is Tuesday" beside "the rollout window is Wednesday"), and it is also the
shape a harmless paraphrase takes -- so the rendered field says ``similar_text``, not "conflict",
and the caller is told which side of the line this sits on.

Why similarity and not the evidence table: the schema has a ``contradicts`` evidence role, but
nothing in the write path produces it (extraction only records ``triggered_by`` and ``supports``).
Marking on a role no producer writes would be a feature that never fires. Recorded contradictions
do still reach the prompt -- E1 puts the role in ``evidence_refs`` -- so what E4 adds is only the
cross-memory pairing.

Known limits, deliberately not papered over:

* Short texts defeat token overlap. "I live in Beijing" and "I moved to Shanghai" share almost no
  bigrams, so they are not flagged. Semantic detection needs a model, which this task excludes.
* Two statements that are genuinely compatible but worded alike are flagged. The label is a hint
  for the reader of the prompt, never a mutation of the store.
"""
from collections import defaultdict
from collections.abc import Iterable
from uuid import UUID

from agent_memory.application.retrieval import RetrievalHit
from agent_memory.domain.lexical import lexical_tokens

# Default Jaccard floor. High on purpose: a low floor turns the field into noise, and noise in a
# prompt is worse than an empty list.
DEFAULT_SIMILARITY = 0.6
# Conflicts one entry may list. The prompt is the scarce resource, as everywhere else here.
MAX_CONFLICTS_PER_HIT = 3


def _subject(hit: RetrievalHit) -> tuple[str, UUID | None, str]:
    return (hit.scope_kind, hit.subject_id, hit.memory_type.value)


def find_conflicts(
    hits: Iterable[RetrievalHit],
    *,
    similarity: float = DEFAULT_SIMILARITY,
    limit: int = MAX_CONFLICTS_PER_HIT,
) -> dict[UUID, tuple[UUID, ...]]:
    """Map each memory to the other memories in the packet it looks like it competes with.

    Deterministic: candidates are ordered by descending similarity, then by memory id, so the cap
    drops the same entries every run. Groups with one member never cost a token comparison.
    """
    grouped: dict[tuple[str, UUID | None, str], list[tuple[RetrievalHit, set[str]]]] = defaultdict(list)
    for hit in hits:
        tokens = lexical_tokens(hit.content)
        if tokens:
            grouped[_subject(hit)].append((hit, tokens))

    found: dict[UUID, list[tuple[float, UUID]]] = defaultdict(list)
    for members in grouped.values():
        if len(members) < 2:
            continue
        for index, (left, left_tokens) in enumerate(members):
            for right, right_tokens in members[index + 1:]:
                if left.content == right.content:
                    continue  # E2 would have merged these; identical text is not a conflict
                union = left_tokens | right_tokens
                if not union:
                    continue
                score = len(left_tokens & right_tokens) / len(union)
                if score < similarity:
                    continue
                if left.memory_id != right.memory_id:
                    found[left.memory_id].append((score, right.memory_id))
                    found[right.memory_id].append((score, left.memory_id))

    return {
        memory_id: tuple(peer for _, peer in sorted(entries, key=lambda e: (-e[0], str(e[1])))[:limit])
        for memory_id, entries in found.items()
    }
