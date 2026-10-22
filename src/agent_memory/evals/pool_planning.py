"""Descriptive inventory and explicitly conditional production planning, never gold adoption."""

import hashlib
import json
import math
from typing import Any

from agent_memory.evals.chinese_expansion import unsegment


def source_record(row: dict[str, Any]) -> tuple[str | None, int, str | None]:
    """Only the BOTH schema used by the frozen candidate generator is eligible."""
    if not isinstance(row.get("conversation"), list) or not row["conversation"]:
        return None, 0, "missing-conversation"
    source = []
    for turn in row["conversation"]:
        if not isinstance(turn, str):
            return None, 0, "invalid-turn"
        utterance = turn.partition("\t")[0]
        speaker, sep, text = utterance.partition(":")
        if not sep or speaker not in ("Usr", "Bot") or not text.strip():
            return None, 0, "invalid-speaker-or-text"
        source.append({"role": "user" if speaker == "Usr" else "assistant", "text": unsegment(text)})
    if not any(s["role"] == "user" for s in source):
        return None, 0, "no-user-turn"
    candidates = 0
    for key in ("user_said_persona", "user_no_said_persona"):
        if not isinstance(row.get(key), list):
            return None, 0, "missing-persona-field"
        for fact in row[key]:
            if not isinstance(fact, str) or not fact.partition(":")[1] or not fact.partition(":")[2].strip():
                return None, 0, "invalid-persona"
            candidates += 1
    if not candidates:
        return None, 0, "no-candidates"
    encoded = json.dumps(source, ensure_ascii=False, sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest(), candidates, None


def production_scenario(
    *, gap: int, candidates_per_dialogue: float, candidate_survival: float,
    precision_assumption: float, batch_size: int = 8,
    prompt_tokens_per_item: float | None = None, completion_tokens_per_item: float | None = None,
) -> dict[str, Any]:
    if gap < 0 or candidates_per_dialogue <= 0 or not 0 < candidate_survival <= 1:
        raise ValueError("positive production assumptions required")
    if not 0 < precision_assumption <= 1 or batch_size <= 0:
        raise ValueError("precision and batch size must be valid")
    needed_survivors = math.ceil(gap / precision_assumption)
    candidates = math.ceil(needed_survivors / candidate_survival)
    conversations = math.ceil(candidates / candidates_per_dialogue)
    # Round conversations up, then budget candidates from that many conversations.
    budget_candidates = math.ceil(conversations * candidates_per_dialogue)
    calls_per_model = math.ceil(budget_candidates / batch_size)
    return {
        "gap": gap, "candidate_survival_assumption": candidate_survival,
        "precision_assumption_not_confidence_bound": precision_assumption,
        "mean_candidates_per_dialogue": candidates_per_dialogue,
        "model_survivors_required": needed_survivors,
        "dialogues_estimated": conversations, "candidate_reviews_each_model": budget_candidates,
        "calls_each_model": calls_per_model, "calls_both_models": 2 * calls_per_model,
        "tokens_both_models_estimated": None if prompt_tokens_per_item is None or completion_tokens_per_item is None
        else math.ceil(2 * budget_candidates * (prompt_tokens_per_item + completion_tokens_per_item)),
        "manual_positive_confirmations_required_for_individual_gold": gap,
        "conditional_only": True, "gold_adopted": False,
    }
