import pytest
from pydantic import ValidationError

from agent_memory.evals.temporal import TemporalEvidenceLabel, TemporalLabel, check


def test_temporary_cannot_keep_and_citation_validation_unchanged():
    item = {"item_id": "x", "source": [{"source_id": "u", "role": "user", "text": "今天在出差"}]}
    quote = {"detail": "出差", "source_id": "u", "quote": "今天在出差"}
    evidence = {
        k: []
        for k in (
            "subject",
            "relation",
            "degree",
            "frequency",
            "quantity",
            "time",
            "diagnostic_certainty",
        )
    }
    evidence.update(subject=[quote], relation=[quote])
    label = TemporalEvidenceLabel(
        item_id="x", label="keep", reason="supported", evidence=evidence, temporal="临时"
    )
    assert check(label, item)["label"] == "discard"
    assert check(label, item)["temporal_removed"]
    bad = label.model_copy(update={"temporal": "长期"})
    item["source"][0]["role"] = "assistant"
    result = check(bad, item)
    assert result["label"] == "uncertain"
    assert not result["citation_valid"]


def test_unknown_temporal_is_invalid():
    with pytest.raises(ValidationError):
        TemporalLabel(item_id="x", temporal="不清楚")


def test_long_term_preserves_original_keep_and_uncertain():
    item = {"item_id": "x", "source": [{"source_id": "u", "role": "user", "text": "一直喜欢集邮"}]}
    quote = {"detail": "集邮", "source_id": "u", "quote": "一直喜欢集邮"}
    evidence = {
        k: []
        for k in (
            "subject",
            "relation",
            "degree",
            "frequency",
            "quantity",
            "time",
            "diagnostic_certainty",
        )
    }
    evidence.update(subject=[quote], relation=[quote])
    label = TemporalEvidenceLabel(
        item_id="x", label="keep", reason="supported", evidence=evidence, temporal="长期"
    )
    assert check(label, item)["label"] == "keep"
    uncertain = label.model_copy(update={"label": "uncertain", "reason": "uncertain"})
    assert check(uncertain, item)["label"] == "uncertain"
