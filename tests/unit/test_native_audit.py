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
