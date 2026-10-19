import csv
import hashlib
import json

import pytest

from agent_memory.evals.human_review import answers, csv_text, digest, finalize
from agent_memory.evals.labeling import review_pack


def prepare(tmp_path):
    items, left, right = (tmp_path / name for name in ("items", "left", "right"))
    items.write_text(
        "".join(
            json.dumps({"item_id": key, "candidate": "虚构事实", "source": "=synthetic-source"})
            + "\n"
            for key in ["a", "b"]
        )
    )
    for path, labels in [(left, ["keep", "keep"]), (right, ["discard", "keep"])]:
        path.write_text(
            "".join(
                json.dumps({"item_id": key, "label": label, "reason": "test"}) + "\n"
                for key, label in zip(["a", "b"], labels, strict=True)
            )
        )
    pack = tmp_path / "pack"
    review_pack(items, left, right, pack)
    (pack / "provenance.json").write_text(
        json.dumps(
            {
                "items_sha256": hashlib.sha256(items.read_bytes()).hexdigest(),
                "labels_sha256": [
                    hashlib.sha256(path.read_bytes()).hexdigest() for path in [left, right]
                ],
            }
        )
    )
    paths = {}
    for task, label in [("arbitration", "keep"), ("audit", "discard")]:
        rows = [
            json.loads(line) for line in (pack / (task + "-blind.jsonl")).read_text().splitlines()
        ]
        for row in rows:
            row.update(human_label=label, human_reason="unit owner decision")
        path = tmp_path / (task + ".jsonl")
        path.write_text("".join(json.dumps(row) + "\n" for row in rows))
        paths[task] = path
    return dict(
        items=items,
        left=left,
        right=right,
        pack=pack,
        **paths,
        reviewer="unit-owner",
        threshold=0.95,
        output=tmp_path / "final",
    )


def test_audit_is_scored_before_applying_owner_corrections(tmp_path):
    args = prepare(tmp_path)
    result = finalize(**args)
    assert result["audit_count"] == 1 and result["human_agreement"] == 0
    assert not result["human_consistency_passed"] and not result["phase_gate_passed"]
    before = json.loads((args["output"] / "before-audit.jsonl").read_text().splitlines()[0])
    after = json.loads((args["output"] / "after-audit.jsonl").read_text().splitlines()[0])
    assert before["label"] == "keep" and after["label"] == "discard"


@pytest.mark.parametrize("mode", ["blank", "changed", "missing"])
def test_incomplete_or_changed_human_answers_cannot_pass(tmp_path, mode):
    args = prepare(tmp_path)
    row = json.loads(args["audit"].read_text())
    if mode == "blank":
        row["human_label"] = None
    if mode == "changed":
        row["candidate"] = "different text"
    args["audit"].write_text("" if mode == "missing" else json.dumps(row) + "\n")
    with pytest.raises(ValueError):
        finalize(**args)
    assert not args["output"].exists()


def test_csv_checks_frozen_source_and_answers(tmp_path):
    args = prepare(tmp_path)
    template = args["pack"] / "audit-blind.jsonl"
    row = json.loads(template.read_text())
    path = tmp_path / "audit.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        columns = [
            "item_id",
            "conversation_id",
            "subject",
            "candidate",
            "source",
            "record_sha256",
            "human_label",
            "human_reason",
        ]
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        values = {key: csv_text(row.get(key, "")) for key in columns}
        values.update(record_sha256=digest(row), human_label="keep", human_reason="unit owner")
        writer.writerow(values)
    assert answers(template, path)["a"].label == "keep"
    path.write_text(
        path.read_text(encoding="utf-8-sig").replace("'=synthetic-source", "changed-source")
    )
    with pytest.raises(ValueError, match="was changed"):
        answers(template, path)
