"""Reproducible synthetic customer timelines; candidate labels require independent review.

No model result or human approval is manufactured by this generator.
"""

import argparse
import json
from pathlib import Path

from agent_memory.evals.datasets import (
    Conversation,
    Document,
    Question,
    conversation_split,
    file_hash,
)

parser = argparse.ArgumentParser()
parser.add_argument("--output", type=Path, required=True)
a = parser.parse_args()
if ".local" not in a.output.resolve().parts:
    parser.error("review corpus stays ignored .local/")
a.output.mkdir(parents=True, exist_ok=False)
a.output.chmod(0o700)
corpus = []
items = []
timeline = []
cities = ["北京", "上海", "杭州", "成都", "广州", "南京", "武汉", "苏州", "厦门", "西安"]
drinks = ["红茶", "绿茶", "乌龙茶", "热牛奶", "无糖豆浆", "白开水"]
hobbies = ["摄影", "跑步", "游泳", "阅读", "登山", "画画", "骑行"]
categories = [
    "single-session",
    "multi-session",
    "temporal-reasoning",
    "knowledge-update",
    "preference",
    "abstention",
]
for i in range(430):
    cid = f"customer-timeline-v1:{i:04d}"
    if i >= 300:
        docs = [
            Document(
                source_id="s1:t1",
                session_id="s1",
                role="user",
                text="你好，谢谢，先这样，再见。",
                occurred_at="2025-01-01T08:00:00+00:00",
            )
        ]
        conv = Conversation(
            conversation_id=cid,
            documents=docs,
            questions=[],
            metadata={"synthetic": True, "negative_design": True, "evidence_level": "session"},
        )
        candidates = ["用户长期喜欢红茶。"]
    else:
        nick = f"虚构顾客{i:04d}"
        old = cities[i % 10]
        new = cities[(i + 3) % 10]
        drink = drinks[i % 6]
        hobby = hobbies[i % 7]
        docs = [
            Document(
                source_id="s1:t1",
                session_id="s1",
                role="user",
                text=f"叫我{nick}。我平时喜欢{hobby}，现在住在{old}。",
                occurred_at="2025-01-01T08:00:00+00:00",
            ),
            Document(
                source_id="s2:t1",
                session_id="s2",
                role="user",
                text=f"以后给我推荐饮品时，优先考虑{drink}，这是我的长期偏好。",
                occurred_at="2025-02-01T08:00:00+00:00",
            ),
            Document(
                source_id="s3:t1",
                session_id="s3",
                role="user",
                text=f"地址更新：三月起我已从{old}搬到{new}，以后按{new}推荐配送。",
                occurred_at="2025-03-01T08:00:00+00:00",
            ),
        ]
        definitions = [
            (f"{nick}的爱好是什么？", hobby, {"s1": 1}),
            (
                f"结合前两次会话，{nick}有什么爱好、偏好什么饮品？",
                f"{hobby}、{drink}",
                {"s1": 1, "s2": 1},
            ),
            (f"2025年1月时{nick}住在哪里？", old, {"s1": 1}),
            (f"2025年3月更新后，{nick}的配送城市是什么？", new, {"s3": 1}),
            (f"给{nick}推荐饮品，应优先考虑什么？", drink, {"s2": 1}),
            (f"{nick}喜欢什么颜色的杯子？", "未提供相关信息", {}),
        ]
        qs = [
            Question(
                question_id=f"{cid}:q{k}",
                text=defs[0],
                answer=defs[1],
                category=cat,
                relevant=defs[2],
                abstention=cat == "abstention",
            )
            for k, (cat, defs) in enumerate(zip(categories, definitions, strict=True))
            if k != i % 6
        ]
        conv = Conversation(
            conversation_id=cid,
            documents=docs,
            questions=qs,
            metadata={"synthetic": True, "evidence_level": "session"},
        )
        candidates = [
            f"用户希望被称为{nick}。",
            f"用户的长期爱好是{hobby}。",
            f"用户在2025年1月住在{old}。",
            f"用户长期偏好饮品{drink}。",
            f"用户在2025年3月搬到{new}。",
        ]
        timeline.append(
            {
                "conversation_id": cid,
                "nickname": nick,
                "hobby": hobby,
                "old_city": old,
                "new_city": new,
                "drink": drink,
            }
        )
    corpus.append(conv)
    for j, candidate in enumerate(candidates):
        items.append(
            {
                "item_id": f"{cid}:candidate:{j}",
                "conversation_id": cid,
                "subject": "当前用户",
                "source": [d.model_dump(mode="json") for d in docs],
                "candidate": candidate,
            }
        )
(a.output / "corpus.jsonl").write_text("".join(c.model_dump_json() + "\n" for c in corpus))
(a.output / "items.jsonl").write_text(
    "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in items)
)
(a.output / "timeline-local.json").write_text(json.dumps(timeline, ensure_ascii=False, indent=2))
(a.output / "split.json").write_text(
    json.dumps(conversation_split([c.conversation_id for c in corpus]), indent=2)
)
manifest = {
    "name": "customer-timeline-v1",
    "synthetic": True,
    "seed": 42,
    "conversations": len(corpus),
    "designed_negative_conversations": 130,
    "negative_ratio": 130 / 430,
    "candidate_facts_positive_design": 1500,
    "questions": sum(len(c.questions) for c in corpus),
    "question_counts": {
        cat: sum(q.category == cat for c in corpus for q in c.questions) for cat in categories
    },
    "human_review_complete": False,
    "model_labels_complete": False,
    "gold_status": "synthetic timeline truth, NOT human-approved extraction gold",
    "files": {p.name: file_hash(p) for p in a.output.iterdir() if p.is_file()},
}
(a.output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
print(json.dumps({k: v for k, v in manifest.items() if k != "files"}, ensure_ascii=False))
