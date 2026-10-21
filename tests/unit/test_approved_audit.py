import csv
import json

import pytest

from agent_memory.evals.approved_audit import (
    FIELDS,
    finalize_joint_audit,
    hypergeometric_interval,
    prepare_joint_audit,
)


def fixture(tmp_path):
    items = tmp_path / "items.jsonl"
    left = tmp_path / "a.jsonl"
    right = tmp_path / "b.jsonl"
    human = tmp_path / "h.jsonl"
    rows = [
        {
            "item_id": str(i),
            "conversation_id": "fixture:" + str(i),
            "subject": "fixture",
            "candidate": "fixture",
            "source": [],
        }
        for i in range(100)
    ]
    labels = [{"item_id": str(i), "label": "keep", "reason": "unit fixture"} for i in range(100)]
    for path, data in [
        (items, rows),
        (left, labels),
        (right, labels),
        (human, [{**labels[0], "label": "discard"}, *labels[1:4]]),
    ]:
        path.write_text("".join(json.dumps(r) + "\n" for r in data))
    pack = tmp_path / ".local" / "pack"
    manifest = prepare_joint_audit(
        items=items, left=left, right=right, prior_human=human, output=pack
    )
    return pack, manifest


def test_blind_table_has_no_labels_and_excludes_all_previously_reviewed_rows(tmp_path):
    pack, m = fixture(tmp_path)
    mapping = json.loads((pack / "opaque-map-private.json").read_text())
    assert not set(mapping.values()) & {"0", "1", "2", "3"}
    assert m["eligible_unreviewed_pool"] == 96 and m["remaining_pool"] == 99
    assert m["sample"] == 72 and m["previous_review_overlap"] == 0
    with (pack / "audit-blind.csv").open(encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        assert reader.fieldnames == list(FIELDS)
        assert all(
            not r["human_label"] and not r["human_reason"] and len(r["item_id"]) == 32
            for r in reader
        )
    with pytest.raises(ValueError, match="missing"):
        finalize_joint_audit(
            pack, pack / "audit-blind.csv", tmp_path / ".local" / "bad", "unit-fixture"
        )


@pytest.mark.parametrize("errors,passed", [(3, True), (4, False)])
def test_new_owner_error_gate_is_count_based_and_ci_is_not_silently_an_extra_gate(
    tmp_path, errors, passed
):
    pack, _manifest = fixture(tmp_path)
    with (pack / "audit-blind.csv").open(encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    for i, row in enumerate(rows):
        row.update(
            human_label="discard" if i < errors else "keep",
            human_reason="unit fixture, not real human audit",
        )
    submitted = tmp_path / "returned.csv"
    with submitted.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    result = finalize_joint_audit(pack, submitted, tmp_path / ".local" / "result", "unit-fixture")
    assert result["passed"] == passed and result["errors"] == errors
    assert result["phase1_accepted"] is False
    assert result["error_rate_population_95"][1] > errors / 72


def test_exact_interval_collapses_for_complete_census():
    assert hypergeometric_interval(0, 10, 10) == (0, 0)
    assert hypergeometric_interval(3, 10, 10) == (3, 3)
