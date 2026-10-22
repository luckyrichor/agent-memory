"""Reject invalid items without turning a provider formatting error into a gold label."""

import json
from typing import Any

from pydantic import ValidationError

from agent_memory.evals.temporal import TemporalEvidenceLabel, check


def uncertain(item_id: str, failure: str, raw: object = None) -> dict[str, Any]:
    source = raw if isinstance(raw, dict) else {}
    temporal = source.get("temporal")
    return {
        "item_id": item_id,
        "label": "uncertain",
        "reason": failure,
        "model_label": source.get("label"),
        "temporal": temporal if temporal in ("长期", "临时") else None,
        "temporal_removed": False,
        "schema_valid": False,
        "citation_valid": False,
        "citation_failures": [failure],
        "reference_count": 0,
        "program_uncertain": True,
    }


def validate_response(content: str, aliases: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """The original strict schema/quote rules apply to every accepted keep.

    No field removal, quote repair, candidate edits or semantic heuristics.
    A bad root/coverage rejects every item; an individually invalid item stays
    program-uncertain. This is not a model's semantic uncertain judgement.
    """
    try:
        root = json.loads(content)
        if not isinstance(root, dict) or set(root) != {"labels"}:
            raise ValueError("invalid root")
        raw = root["labels"]
        if not isinstance(raw, list) or len(raw) != len(aliases):
            raise ValueError("invalid coverage")
        ids = [r.get("item_id") if isinstance(r, dict) else None for r in raw]
        if any(not isinstance(key, str) for key in ids):
            raise ValueError("invalid identity")
        if len(set(ids)) != len(ids) or set(ids) != set(aliases):
            raise ValueError("invalid identity coverage")
    except (TypeError, ValueError):
        return [uncertain(r["item_id"], "response-invalid") for r in aliases.values()]
    result = []
    for value in raw:
        item = aliases[value["item_id"]]
        try:
            label = TemporalEvidenceLabel.model_validate(value)
        except ValidationError:
            result.append(uncertain(item["item_id"], "schema-invalid", value))
            continue
        original = label.model_copy(update={"item_id": item["item_id"]})
        decision = check(original, item)
        decision.update(schema_valid=True, program_uncertain=not decision["citation_valid"])
        result.append(decision)
    return result
