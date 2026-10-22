"""Long-term-only annotation extension; original quote checks remain authoritative."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from agent_memory.evals.evidence_v3 import EvidenceLabel, validate_quotes


class TemporalLabel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    item_id: str
    temporal: Literal["长期", "临时"]


class TemporalBatch(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    labels: list[TemporalLabel]


class TemporalEvidenceLabel(EvidenceLabel):
    temporal: Literal["长期", "临时"]


class TemporalEvidenceBatch(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    labels: list[TemporalEvidenceLabel]


def check(label: TemporalEvidenceLabel, item: dict[str, Any]) -> dict[str, Any]:
    original = EvidenceLabel.model_validate(label.model_dump(exclude={"temporal"}))
    result = validate_quotes(original, item)
    result["temporal"] = label.temporal
    result["temporal_removed"] = label.temporal == "临时" and result["label"] == "keep"
    if result["temporal_removed"]:
        result.update(label="discard", reason="temporary")
    return result
