import json
from collections import Counter

from agent_memory.evals.synthetic_hard import build_hardset


def read(path):
    return [json.loads(s) for s in path.read_text().splitlines()]


def test_hardset_balances_shortcuts_hides_truth_and_has_real_counterfactuals(tmp_path):
    first = tmp_path / ".local" / "first"
    second = tmp_path / ".local" / "second"
    a = build_hardset(first, count=10)
    b = build_hardset(second, count=10)
    assert a["artifact_digest"] == b["artifact_digest"]
    labels = {r["item_id"]: r["label"] for r in read(first / "constructor-truth-private.jsonl")}
    strata = {}
    for r in read(first / "items.jsonl"):
        assert set(r) == {"item_id", "conversation_id", "subject", "candidate", "source"}
        assert len(r["item_id"]) == 32
        key = (len(r["source"]), sum(len(d["text"]) for d in r["source"]))
        strata.setdefault(key, Counter())[labels[r["item_id"]]] += 1
    assert all(v["keep"] == v["discard"] for v in strata.values())
    base = {r["item_id"]: r for r in read(first / "items.jsonl")}
    controls = {r["item_id"]: r for r in read(first / "controls.jsonl")}
    for truth in read(first / "control-truth-private.jsonl"):
        before, after = base[truth["base_item_id"]], controls[truth["item_id"]]
        assert before["candidate"] == after["candidate"]
        if truth["control"] == "shuffle":
            assert sorted(before["source"], key=lambda d: d["source_id"]) == sorted(
                after["source"], key=lambda d: d["source_id"]
            )
            assert truth["expected"] == truth["original"]
        elif truth["control"] == "counterfactual":
            assert truth["expected"] != truth["original"]
            old = {d["source_id"]: d for d in before["source"]}
            changed = [d for d in after["source"] if old[d["source_id"]] != d]
            assert len(changed) == 1
            assert len(changed[0]["text"]) == 128
        else:
            assert truth["expected"] == "discard"
    assert all(
        not r["human_label"] and not r["human_reason"]
        for r in read(first / "owner-audit-proposed.jsonl")
    )
    assert a["model_control_runs"] == a["owner_annotations"] == 0
    assert a["replacement_approved"] is False


def test_query_proposal_keeps_frozen_other_sources_and_counts(tmp_path):
    from agent_memory.evals.synthetic_hard import propose_query_replacement

    hard = tmp_path / ".local" / "hard"
    build_hardset(hard, count=10)
    frozen = tmp_path / ".local" / "frozen"
    frozen.mkdir()
    queries = read(hard / "queries-proposed.jsonl")
    kept = {"question_id": "original", "conversation_id": "kept", "category": "preference"}
    (frozen / "queries.jsonl").write_text("".join(json.dumps(q) + "\n" for q in queries + [kept]))
    (frozen / "contexts.jsonl").write_text(
        json.dumps({"conversation_id": "kept", "documents": []}) + "\n"
    )
    (frozen / "split.json").write_text(json.dumps({"dev": ["kept"], "test": []}))
    before = (frozen / "queries.jsonl").read_bytes()
    output = tmp_path / ".local" / "proposal"
    result = propose_query_replacement(frozen, hard, output)
    assert result["replaced"] == 30 and result["unchanged_other_queries"] == 1
    assert kept in read(output / "queries.jsonl")
    assert (frozen / "queries.jsonl").read_bytes() == before
    assert result["approved"] is result["activated"] is False
