import json

from agent_memory.evals.temporal_output import validate_response


def fixture():
    item = {
        "item_id": "original",
        "source": [{"source_id": "u", "role": "user", "text": "长期喜欢集邮"}],
    }
    quote = {"detail": "集邮", "source_id": "u", "quote": "长期喜欢集邮"}
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
    evidence.update(subject=[quote.copy()], relation=[quote.copy()])
    raw = {
        "item_id": "i0",
        "label": "keep",
        "reason": "supported",
        "temporal": "长期",
        "evidence": evidence,
    }
    return item, raw


def test_strict_valid_item_keeps_original_quote_check():
    item, raw = fixture()
    result = validate_response(json.dumps({"labels": [raw]}), {"i0": item})[0]
    assert result["item_id"] == "original"
    assert result["label"] == "keep"
    assert result["schema_valid"] and result["citation_valid"]


def test_extra_quote_metadata_rejected_not_stripped_other_item_preserved():
    item, bad = fixture()
    second, good = fixture()
    second["item_id"] = "second"
    good["item_id"] = "i1"
    bad["evidence"]["subject"][0]["session_id"] = "not-allowed"
    values = validate_response(json.dumps({"labels": [bad, good]}), {"i0": item, "i1": second})
    assert values[0]["label"] == "uncertain" and not values[0]["schema_valid"]
    assert values[0]["program_uncertain"]
    assert values[1]["label"] == "keep"
    assert "session_id" in bad["evidence"]["subject"][0]


def test_missing_or_duplicate_identity_rejects_complete_response():
    item, raw = fixture()
    result = validate_response(json.dumps({"labels": [raw, raw]}), {"i0": item})
    assert result[0]["label"] == "uncertain"
    assert result[0]["reason"] == "response-invalid"


def test_wrong_speaker_is_still_invalid():
    item, raw = fixture()
    item["source"][0]["role"] = "assistant"
    result = validate_response(json.dumps({"labels": [raw]}), {"i0": item})[0]
    assert result["label"] == "uncertain" and not result["citation_valid"]


def test_bad_root_or_json_does_not_invent_negative_label():
    item, raw = fixture()
    for content in ("not-json", json.dumps({"labels": [raw], "extra": True})):
        result = validate_response(content, {"i0": item})[0]
        assert result["label"] == "uncertain" and not result["schema_valid"]


def test_invalid_temporal_not_defaulted_to_long_term():
    item, raw = fixture()
    raw["temporal"] = "unknown"
    result = validate_response(json.dumps({"labels": [raw]}), {"i0": item})[0]
    assert result["temporal"] is None
    assert result["label"] == "uncertain"
