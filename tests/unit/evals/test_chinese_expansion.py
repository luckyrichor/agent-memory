import json
import zipfile
from pathlib import Path

import pytest

from agent_memory.evals.annotate import require_disabled_thinking
from agent_memory.evals.chinese_expansion import (
    diagnose,
    dulemon,
    ecd,
    frozen_extension,
    inherit_source_split,
    read_jsonl,
    unsegment,
    write_jsonl,
)
from agent_memory.evals.reference_review import finalize_reference, make_reference_pack


def test_append_only_split_and_source_rendering():
    old = {"dev": ["old:1"], "test": ["old:2", "old:3"]}
    new = [f"new:{i}" for i in range(10)]
    split = frozen_extension(old, new)
    assert split["dev"][:1] == old["dev"]
    assert split["test"][:2] == old["test"]
    assert len(split["dev"]) == 4 and len(split["test"]) == 9
    assert not set(split["dev"]) & set(split["test"])
    assert split == frozen_extension(old, list(reversed(new)))
    with pytest.raises(ValueError):
        frozen_extension(old, ["old:1", "new"])
    assert unsegment(" 我 喜欢 红 茶 ") == "我喜欢红茶"
    assert inherit_source_split(old, {"alias:1": "old:1", "alias:2": "old:3"}) == {
        "dev": ["alias:1"],
        "test": ["alias:2"],
    }
    with pytest.raises(ValueError):
        inherit_source_split(old, {"alias": "not-frozen"})


def test_unused_dulemon_references_are_blind_and_not_model_filtered(tmp_path):
    archive = tmp_path / "source.zip"
    row = {
        "conversation": ["Usr: 我 喜欢 茶\tU1", "Bot: 好 的"],
        "user_said_persona": ["U1: 我 喜欢 茶"],
        "user_no_said_persona": ["U2: 我 喜欢 咖 啡"],
    }
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("DuLeMon/both/train.json", "\n".join(json.dumps(row) for _ in range(5)))
    old = tmp_path / "old.jsonl"
    write_jsonl(
        old,
        [
            {"conversation_id": "dulemon-both-train:0000"},
            {"conversation_id": "dulemon-both-train:0000:assistant-only"},
        ],
    )
    result = dulemon(archive, old, tmp_path / "new", count=3)
    assert result["overlap"] == 0 and 0 not in result["new_indices"]
    assert result["reference_keep"] == result["reference_discard"] == 3
    assert result["reference_negative_conversations"] == 0
    items = read_jsonl(tmp_path / "new/items.jsonl")
    assert all("user_said" not in str(r) and "user_no_said" not in str(r) for r in items)
    assert all(
        set(r) == {"item_id", "conversation_id", "subject", "source", "candidate"} for r in items
    )
    assert len({r["item_id"] for r in items}) == 6


def test_diagnosis_is_disjoint_and_does_not_invent_fluency_evidence(tmp_path):
    items, a, b = (tmp_path / s for s in ("items", "a", "b"))
    write_jsonl(items, [{"item_id": str(i)} for i in range(5)])
    labels = [
        {"item_id": str(i), "label": "discard", "reason": r}
        for i, r in enumerate(("attribution", "temporary", "missing", "supported", "missing"))
    ]
    labels[3]["label"] = "keep"
    write_jsonl(a, labels)
    labels[-1] = {"item_id": "4", "label": "keep", "reason": "supported"}
    write_jsonl(b, labels)
    result = diagnose(items, a, b)
    assert result["joint_keep"] == 1 and result["not_joint_keep"] == 4
    assert sum(v["count"] for v in result["categories"].values()) == 4
    assert result["categories"]["候选表述不通顺"]["count"] == 0
    assert result["fluency_assessed"] is False


def test_ecd_rejects_wrong_size_before_creating_output(tmp_path):
    archive = tmp_path / "small.zip"
    archive.write_bytes(b"not-the-frozen-archive")
    with pytest.raises(ValueError, match="size mismatch"):
        ecd(archive, tmp_path / "output")
    assert not (tmp_path / "output").exists()


@pytest.mark.parametrize("content,tokens", [("hidden reasoning", 0), (None, 3), ("reasoning", 4)])
def test_disabled_thinking_guard_rejects_observed_provider_violation(content, tokens):
    with pytest.raises(RuntimeError, match="frozen disabled-thinking"):
        require_disabled_thinking(
            {
                "choices": [{"message": {"reasoning_content": content}}],
                "usage": {"completion_tokens_details": {"reasoning_tokens": tokens}},
            }
        )


def test_disabled_thinking_guard_accepts_nonreasoning_response():
    require_disabled_thinking(
        {
            "choices": [{"message": {"content": "{}"}}],
            "usage": {"completion_tokens_details": {"reasoning_tokens": 0}},
        }
    )


def reference_fixture(tmp_path: Path):
    items, refs, a, b = (tmp_path / s for s in ("items", "refs", "a", "b"))
    write_jsonl(
        items,
        [
            {
                "item_id": str(i),
                "conversation_id": "conv",
                "subject": "user",
                "source": [],
                "candidate": "fixture",
            }
            for i in range(10)
        ],
    )
    native = [{"item_id": str(i), "label": "keep", "reason": "native"} for i in range(10)]
    write_jsonl(refs, native)
    write_jsonl(a, native)
    # One model rejects a native positive: the source reference must not be removed.
    native[0] = {"item_id": "0", "label": "discard", "reason": "missing"}
    write_jsonl(b, native)
    pack = tmp_path / "pack"
    result = make_reference_pack(items, refs, pack, models=(a, b))
    return items, refs, a, b, pack, result


def test_reference_review_retains_native_references_and_requires_owner_answers(tmp_path):
    items, refs, a, b, pack, result = reference_fixture(tmp_path)
    assert result["arbitration_count"] == result["audit_count"] == 1
    assert all(
        "human_label" in r and r["human_label"] is None
        for r in read_jsonl(pack / "audit-blind.jsonl")
    )
    assert read_jsonl(refs)[0]["label"] == "keep"
    with pytest.raises(ValueError, match="missing or invalid"):
        finalize_reference(
            items=items,
            references=refs,
            pack=pack,
            arbitration=pack / "arbitration-blind.csv",
            audit=pack / "audit-blind.csv",
            reviewer="unit-owner",
            model_left=a,
            model_right=b,
            output=tmp_path / "bad",
        )


def test_reference_audit_compares_before_corrections_and_checks_model_hashes(tmp_path):
    items, refs, a, b, pack, _ = reference_fixture(tmp_path)
    submitted = {}
    for task in ("arbitration", "audit"):
        rows = read_jsonl(pack / f"{task}-blind.jsonl")
        for row in rows:
            row.update(
                human_label="discard" if task == "audit" else "keep", human_reason="unit fixture"
            )
        submitted[task] = tmp_path / task
        write_jsonl(submitted[task], rows)
    kwargs = {
        "items": items,
        "references": refs,
        "pack": pack,
        "arbitration": submitted["arbitration"],
        "audit": submitted["audit"],
        "reviewer": "unit-owner",
        "output": tmp_path / "complete",
    }
    with pytest.raises(ValueError, match="omitted"):
        finalize_reference(**kwargs)
    result = finalize_reference(**kwargs, model_left=a, model_right=b)
    assert result["human_agreement"] == 0 and result["human_consistency_passed"] is False
    assert result["phase_gate_passed"] is False
    assert read_jsonl(tmp_path / "complete/after-audit.jsonl") != read_jsonl(
        tmp_path / "complete/before-audit.jsonl"
    )
