import json
from pathlib import Path

import pytest

from agent_memory.evals.datasets import (
    Conversation,
    Document,
    Question,
    conversation_split,
    locomo,
    longmemeval,
    validate_evidence,
)
from agent_memory.evals.labeling import review_pack
from agent_memory.evals.runner import save_report, score


def test_conversation_split_keeps_related_items_together_and_is_order_independent():
    ids = [f"c{i}" for i in range(10)]
    result = conversation_split(ids)
    assert len(result["dev"]) == 3 and len(result["test"]) == 7
    assert not set(result["dev"]) & set(result["test"])
    assert result == conversation_split(list(reversed(ids)))
    with pytest.raises(ValueError):
        conversation_split(["a", "a"])


def test_lme_preserves_duplicate_session_occurrences_and_assistant_attribution(tmp_path):
    source = tmp_path / "source.json"
    source.write_text(
        json.dumps(
            [
                {
                    "question_id": "q",
                    "question_type": "multi-session",
                    "question": "where?",
                    "answer": "not indexed",
                    "question_date": "2020/01/01",
                    "haystack_session_ids": ["s", "s"],
                    "haystack_dates": ["2020/01/01"] * 2,
                    "haystack_sessions": [
                        [{"role": "user", "content": "first"}],
                        [{"role": "assistant", "content": "second"}],
                    ],
                    "answer_session_ids": ["s"],
                }
            ]
        )
    )
    conv = next(longmemeval(source))
    assert len({d.source_id for d in conv.documents}) == 2
    assert conv.documents[1].role == "assistant"
    assert conv.questions[0].relevant == {"s": 1}
    assert validate_evidence(conv) == []
    assert "not indexed" not in [d.text for d in conv.documents]


def test_locomo_unresolvable_gold_is_not_scored_as_failure(tmp_path):
    source = tmp_path / "source.json"
    source.write_text(
        json.dumps(
            [
                {
                    "sample_id": "a",
                    "conversation": {
                        "session_1": [{"dia_id": "D1:1", "speaker": "A", "text": "fact"}],
                    },
                    "qa": [{"question": "q", "answer": "a", "category": 1, "evidence": ["D1:99"]}],
                }
            ]
        )
    )
    conv = next(locomo(source))
    assert conv.documents[0].role == "source"
    assert not conv.questions[0].evidence_available
    assert validate_evidence(conv) == ["D1:99"]


def test_runner_hand_scores_actual_saved_ranking_and_reports_missing(tmp_path):
    conv = Conversation(
        conversation_id="a",
        documents=[Document(source_id="a", session_id="s", role="user", text="gold fact")],
        questions=[
            Question(question_id="q1", text="q", answer="a", category="fact", relevant={"a": 1}),
            Question(question_id="q2", text="q", answer="a", category="fact", relevant={"a": 1}),
            Question(
                question_id="q3",
                text="q",
                answer="",
                category="abstention",
                relevant={},
                abstention=True,
            ),
        ],
    )
    dataset, predictions, config = [
        tmp_path / n for n in ["data.jsonl", "pred.jsonl", "config.json"]
    ]
    dataset.write_text(conv.model_dump_json() + "\n")
    predictions.write_text(
        json.dumps({"question_id": "q1", "ranked_source_ids": ["x", "a"]})
        + "\n"
        + json.dumps({"question_id": "q3", "ranked_source_ids": []})
        + "\n"
    )
    config.write_text("{}")
    result = score(dataset, predictions)
    assert result["metrics"]["RT1@1"]["value"] == 0
    assert result["metrics"]["RT1@3"]["value"] == 1
    assert result["metrics"]["RT6"]["value"] == 1
    assert result["cases"][1]["status"] == "missing_prediction"
    assert result["scored_count"] == 2
    output = tmp_path / "run"
    save_report(output, dataset, predictions, config, "direct", {"RT1"})
    assert "gold fact" not in (output / "report.json").read_text()
    with pytest.raises(FileExistsError):
        save_report(output, dataset, predictions, config, "direct", {"RT1"})
    with pytest.raises(ValueError, match="unavailable"):
        save_report(tmp_path / "unsupported", dataset, predictions, config, "direct", {"SC1"})


def test_blind_review_preserves_labels_for_real_owner(tmp_path):
    items, a, b = [tmp_path / n for n in ["items", "a", "b"]]
    items.write_text(
        "".join(json.dumps({"item_id": str(i), "source": "text"}) + "\n" for i in range(10))
    )

    def write_labels(path: Path, changed: bool):
        path.write_text(
            "".join(
                json.dumps(
                    {
                        "item_id": str(i),
                        "label": "discard" if changed and i == 0 else "keep",
                        "reason": "model reason",
                    }
                )
                + "\n"
                for i in range(10)
            )
        )

    write_labels(a, False)
    write_labels(b, True)
    review_pack(items, a, b, tmp_path / "review")
    review = tmp_path / "review"
    conflict = json.loads((review / "arbitration-blind.jsonl").read_text())
    assert conflict["item_id"] == "0" and conflict["human_label"] is None
    assert "model reason" not in json.dumps(conflict)
    result = json.loads((review / "model-agreement.json").read_text())
    assert result["agreement"] == 0.9 and result["kappa"] == 0
    assert not result["human_review_complete"]
