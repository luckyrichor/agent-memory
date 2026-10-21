"""Generated fixtures only; no source data or human labels in Git."""

import json

from agent_memory.evals.chinese_queries import CATEGORIES, build_queries


def test_all_six_types_preserve_source_splits_and_never_put_answers_into_documents(tmp_path):
    root = tmp_path / "normalized"
    root.mkdir()
    timeline = tmp_path / "timeline"
    timeline.mkdir()

    def write(p, rows):
        p.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))

    doc = {"source_id": "d", "session_id": "s", "role": "source", "text": "unit fixture"}
    perlt = {
        "conversation_id": "perltqa:fixture",
        "documents": [doc],
        "questions": [
            {
                "question_id": f"p{i}",
                "text": f"测试问{i}",
                "answer": "答案不得进入索引",
                "category": "events",
                "relevant": {"d": 1},
                "abstention": False,
            }
            for i in range(1000)
        ],
        "metadata": {"evidence_level": "source_record"},
    }
    write(root / "perltqa_zh.jsonl", [perlt])
    dulemon = [
        {
            "conversation_id": f"d{i}",
            "documents": [doc],
            "questions": [],
            "metadata": {
                "evidence_level": "turn",
                "personas": {
                    "user_said_persona": ["U1:我喜欢跑步"],
                    "user_no_said_persona": ["U2:我喜欢茶"],
                },
                "persona_evidence": {"U1": ["d"]},
            },
        }
        for i in range(250)
    ]
    write(root / "dulemon.jsonl", dulemon)
    synth = [
        {
            "conversation_id": f"t{i}",
            "documents": [doc],
            "metadata": {"evidence_level": "session"},
            "questions": [
                {
                    "question_id": f"t{i}:q{c}",
                    "text": f"虚构问题{c}",
                    "answer": "虚构",
                    "category": c,
                    "relevant": {"s": 1},
                    "abstention": False,
                }
                for c in CATEGORIES[1:4]
            ],
        }
        for i in range(250)
    ]
    write(timeline / "corpus.jsonl", synth)
    for path, ids in [
        (root / "perltqa_zh-split.json", ["perltqa:fixture"]),
        (root / "dulemon-split.json", [r["conversation_id"] for r in dulemon]),
        (timeline / "split.json", [r["conversation_id"] for r in synth]),
    ]:
        path.write_text(
            json.dumps({"dev": ids[: max(1, len(ids) // 3)], "test": ids[max(1, len(ids) // 3) :]})
        )
    out = tmp_path / ".local" / "queries"
    result = build_queries(root, timeline, out)
    assert result["queries"] == 2250
    assert result["real_dialogue_derived_queries"] == 500
    assert all(n >= 150 for n in result["categories"].values())
    assert result["scale_target_pass"] and not result["quality_gate_pass"]
    assert "答案不得进入索引" not in (out / "contexts.jsonl").read_text()
    split = json.loads((out / "split.json").read_text())
    assert not set(split["dev"]) & set(split["test"])
    assert (
        len(list(map(json.loads, (out / "query-audit-blind.jsonl").read_text().splitlines())))
        == 225
    )
