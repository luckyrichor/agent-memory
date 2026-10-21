import json

import pytest

from agent_memory.evals.native_audit import finalize_native_audit
from agent_memory.evals.reference_review import make_reference_pack


@pytest.mark.parametrize(
    "mismatch,expected_full,expected_count", [(False, True, 100), (True, False, 9)]
)
def test_frozen_reference_denominator_and_failure_subset(
    tmp_path, mismatch, expected_full, expected_count
):
    items = tmp_path / "items.jsonl"
    refs = tmp_path / "references.jsonl"
    items.write_text(
        "".join(
            json.dumps(
                {
                    "item_id": str(i),
                    "conversation_id": "synthetic-fixture",
                    "subject": "test",
                    "candidate": "fixture",
                    "source": [],
                }
            )
            + "\n"
            for i in range(100)
        )
    )
    refs.write_text(
        "".join(
            json.dumps({"item_id": str(i), "label": "keep", "reason": "fixture"}) + "\n"
            for i in range(100)
        )
    )
    pack = tmp_path / "pack"
    make_reference_pack(items, refs, pack)
    rows = [json.loads(line) for line in (pack / "audit-blind.jsonl").read_text().splitlines()]
    for i, row in enumerate(rows):
        row["human_label"] = "discard" if mismatch and i == 0 else "keep"
        row["human_reason"] = "synthetic unit fixture, not an owner review"
    submitted = tmp_path / "submitted.jsonl"
    submitted.write_text("".join(json.dumps(row) + "\n" for row in rows))
    result = finalize_native_audit(
        items=items,
        references=refs,
        pack=pack,
        submitted=submitted,
        reviewer="unit-fixture-only",
        output=tmp_path / ".local" / "result",
    )
    assert result["native_reference_accepted"] == expected_full
    assert result["usable_positive_memory_points"] == expected_count
    assert result["frozen_reference_agreement"] == (0.9 if mismatch else 1.0)
    assert result["phase_gate_passed"] is False
    assert result["full_sample_agreement_lower"] == result["frozen_reference_agreement"]
    assert result["full_sample_agreement_upper"] == result["frozen_reference_agreement"]


@pytest.mark.parametrize("mismatch", [False, True])
def test_partial_owner_rows_only_and_blank_rows_never_become_votes(tmp_path, mismatch):
    items = tmp_path / "items.jsonl"
    refs = tmp_path / "references.jsonl"
    items.write_text(
        "".join(
            json.dumps(
                {
                    "item_id": str(i),
                    "conversation_id": "unit-fixture",
                    "subject": "fixture",
                    "candidate": "fixture",
                    "source": [],
                }
            )
            + "\n"
            for i in range(100)
        )
    )
    refs.write_text(
        "".join(
            json.dumps({"item_id": str(i), "label": "keep", "reason": "fixture"}) + "\n"
            for i in range(100)
        )
    )
    pack = tmp_path / "pack"
    make_reference_pack(items, refs, pack)
    rows = [json.loads(s) for s in (pack / "audit-blind.jsonl").read_text().splitlines()]
    for i, r in enumerate(rows[:7]):
        r["human_label"] = "discard" if mismatch and i == 0 else "keep"
        r["human_reason"] = "synthetic test fixture, not owner evidence"
    returned = tmp_path / "return.jsonl"
    returned.write_text("".join(json.dumps(r) + "\n" for r in rows))
    result = finalize_native_audit(
        items=items,
        references=refs,
        pack=pack,
        submitted=returned,
        reviewer="unit-fixture-only",
        output=tmp_path / ".local" / "result",
    )
    assert result["audit_count"] == 7
    assert result["unchecked_count"] == 3
    assert result["full_sample_agreement_lower"] == ((6 if mismatch else 7) / 10)
    assert result["full_sample_agreement_upper"] == ((9 if mismatch else 10) / 10)
    assert result["frozen_reference_agreement"] == (6 / 7 if mismatch else 1)
    assert result["usable_positive_memory_points"] == (6 if mismatch else 100)


def test_blank_duplicate_and_source_tampering_are_not_hidden_by_partial_mode(tmp_path):
    from agent_memory.evals.human_review import answers

    template = tmp_path / "template.jsonl"
    row = {"item_id": "a", "candidate": "fixture", "human_label": None, "human_reason": None}
    template.write_text(json.dumps(row) + "\n")
    submitted = tmp_path / "submitted.jsonl"
    submitted.write_text((json.dumps(row) + "\n") * 2)
    with pytest.raises(ValueError, match="coverage"):
        answers(template, submitted, allow_blank=True)
    row["candidate"] = "changed"
    submitted.write_text(json.dumps(row) + "\n")
    with pytest.raises(ValueError, match="changed"):
        answers(template, submitted, allow_blank=True)
    row["candidate"] = "fixture"
    row["human_label"] = "keep"  # half-filled is invalid, not a blank vote
    submitted.write_text(json.dumps(row) + "\n")
    with pytest.raises(ValueError, match="missing"):
        answers(template, submitted, allow_blank=True)
