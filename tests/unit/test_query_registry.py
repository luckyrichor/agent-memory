import json

import pytest

from agent_memory.evals.datasets import file_hash
from agent_memory.evals.query_registry import materialize_active_queries
from agent_memory.evals.runner import score


def test_activated_flow_queries_cannot_contaminate_quality_aggregate(tmp_path):
    root = tmp_path / ".local"
    root.mkdir()
    source = root / "contexts.jsonl"
    queries = root / "queries.jsonl"
    manifest = root / "manifest.json"
    source.write_text(
        json.dumps(
            {
                "conversation_id": "c",
                "documents": [
                    {
                        "source_id": "s",
                        "session_id": "x",
                        "role": "user",
                        "text": "fictional fixture",
                    }
                ],
            }
        )
        + "\n"
    )
    qs = [
        {
            "question_id": cat,
            "conversation_id": "c",
            "category": cat,
            "text": "fixture",
            "answer": "fixture",
            "relevant": {"s": 1},
        }
        for cat in ("preference", "multi-session")
    ]
    queries.write_text("".join(json.dumps(r) + "\n" for r in qs))
    config = {
        "active": True,
        "owner_approved": True,
        "version": "unit-v2",
        "flow_only_categories": ["multi-session"],
        "files": {
            k: {"path": str(p), "sha256": file_hash(p)}
            for k, p in [("contexts", source), ("queries", queries)]
        },
    }
    manifest.write_text(json.dumps(config))
    out = root / "corpus.jsonl"
    r = materialize_active_queries(manifest, out)
    assert r["queries"] == 2
    predictions = root / "predictions.jsonl"
    predictions.write_text(
        "".join(
            json.dumps({"question_id": cat, "ranked_source_ids": ids}) + "\n"
            for cat, ids in [("preference", []), ("multi-session", ["s"])]
        )
    )
    scored = score(out, predictions)
    assert scored["metrics"]["RT1@10"]["value"] == 0
    assert "multi-session" not in scored["by_type"]
    assert scored["flow_only_by_type"]["multi-session"]["RT1@10"]["value"] == 1
    assert scored["flow_only_question_count"] == 1
    queries.write_text("tampered")
    with pytest.raises(ValueError, match="hash changed"):
        materialize_active_queries(manifest, root / "bad.jsonl")
