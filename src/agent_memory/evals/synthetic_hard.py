"""Independent adversarial synthetic fixtures, never human gold or frozen-label replacements."""

import hashlib
import json
import random
from collections import Counter
from pathlib import Path
from typing import Any

from agent_memory.evals.datasets import file_hash

STATUS = "流程验证，不作质量证据"
CATEGORIES = ("temporal-reasoning", "knowledge-update", "multi-session")


def build_hardset(output: Path, *, seed: int = 20261021, count: int = 300) -> dict[str, Any]:
    if ".local" not in output.resolve().parts or count < 10:
        raise ValueError("private output and at least ten synthetic conversations required")
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    rng = random.Random(seed)

    def opaque() -> str:
        return f"{rng.getrandbits(128):032x}"

    def padded(text: str) -> str:
        if len(text) > 128:
            raise ValueError("source too long for balanced fixture")
        return text + " " * (128 - len(text))

    def write(name: str, rows: list[dict[str, Any]]) -> None:
        (output / name).write_text(
            "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows)
        )

    contexts: list[dict[str, Any]] = []
    items: list[dict[str, Any]] = []
    truth: list[dict[str, Any]] = []
    controls: list[dict[str, Any]] = []
    control_truth: list[dict[str, Any]] = []
    queries: list[dict[str, Any]] = []
    cities = ["北京", "上海", "杭州", "成都", "南京", "武汉", "苏州", "厦门"]
    drinks = ["红茶", "绿茶", "豆浆", "牛奶"]
    hobbies = ["摄影", "跑步", "游泳", "阅读"]
    for i in range(count):
        cid = opaque()
        old, new = rng.sample(cities, 2)
        drink, friend_drink = rng.sample(drinks, 2)
        hobby = rng.choice(hobbies)
        # Equal document counts and character lengths across every label in each stratum.
        n = 6 if i % 2 == 0 else 9
        specs = [
            ("2025-01-03", f"我自己一直住在{old}，这是常住地，暂时没有搬家安排。"),
            ("2025-02-04", f"朋友小林一直喜欢{friend_drink}，这是他的偏好；别把他的喜好当成我的。"),
            ("2025-02-16", f"只有今天这次活动我临时选择{hobby}，不是日常爱好，也别用于以后推荐。"),
            ("2025-03-02", f"从三月开始我的常住地改成{new}了，一月的信息现在过时了。"),
            ("2025-03-15", f"说的是我自己：我长期喜欢{drink}，以后推荐饮品请按这个偏好。"),
            ("2025-04-01", "刚才的快递已经收到了，谢谢，今天没有别的事情。"),
        ]
        specs.extend(
            (f"2025-04-{d:02d}", "今天客服已经答复临时订单问题，这次事项结束，无须以后沿用。")
            for d in range(2, n - 4)
        )
        docs = [
            {
                "source_id": opaque(),
                "session_id": opaque(),
                "role": "user",
                "text": padded(t),
                "occurred_at": day + "T08:00:00+00:00",
            }
            for day, t in specs
        ]
        old_id, new_id, drink_id = docs[0]["source_id"], docs[3]["source_id"], docs[4]["source_id"]
        rng.shuffle(docs)
        contexts.append({"conversation_id": cid, "documents": docs})
        definitions = [
            (f"用户从三月起常住{new}。", "keep", "current-address", new_id),
            (f"用户长期喜欢{drink}。", "keep", "self-preference", drink_id),
            (
                f"用户长期喜欢{friend_drink}。",
                "discard",
                "other-person",
                next(d["source_id"] for d in docs if d["occurred_at"].startswith(specs[1][0])),
            ),
            (
                f"用户长期爱好{hobby}。",
                "discard",
                "temporary",
                next(d["source_id"] for d in docs if d["occurred_at"].startswith(specs[2][0])),
            ),
        ]
        for candidate, label, kind, evidence in definitions:
            item = {
                "item_id": opaque(),
                "conversation_id": cid,
                "subject": "当前用户",
                "candidate": candidate,
                "source": docs,
            }
            items.append(item)
            truth.append(
                {
                    "item_id": item["item_id"],
                    "label": label,
                    "kind": kind,
                    "evidence": evidence,
                    "provenance": "constructor-only-not-an-annotation",
                }
            )
            shuffled = list(docs)
            rng.shuffle(shuffled)
            # No constructor labels, kind names, linked base IDs or truth in model-visible records.
            for mode in ("shuffle", "mask", "counterfactual"):
                changed = [dict(d) for d in shuffled]
                if mode == "mask":
                    for d in changed:
                        d["text"] = padded("该轮内容已遮蔽，无法提供任何用户事实。")
                    expected = "discard"
                elif mode == "counterfactual":
                    if kind == "current-address":
                        changed_text = (
                            f"从三月开始朋友小林常住{new}，不是我的住址，我的住址未提供。"
                        )
                        target = next(
                            d["source_id"]
                            for d in docs
                            if d["occurred_at"].startswith("2025-03-02")
                        )
                    elif kind == "self-preference":
                        changed_text = (
                            f"说的是朋友：他长期喜欢{drink}，我的饮品偏好没有提供，请勿推断。"
                        )
                        target = drink_id
                    elif kind == "other-person":
                        # Counterfactual changes who owns the stable preference.
                        changed_text = f"我自己也长期喜欢{friend_drink}，这是我的偏好，不是仅仅朋友的，以后按此推荐。"
                        target = next(
                            d["source_id"]
                            for d in docs
                            if d["occurred_at"].startswith("2025-02-04")
                        )
                    else:
                        changed_text = (
                            f"这次说的是我长期的爱好{hobby}，不是临时活动，以后请按这个推荐。"
                        )
                        target = next(
                            d["source_id"]
                            for d in docs
                            if d["occurred_at"].startswith("2025-02-16")
                        )
                    for d in changed:
                        if d["source_id"] == target:
                            d["text"] = padded(changed_text)
                    expected = "discard" if label == "keep" else "keep"
                else:
                    expected = label
                control = {
                    "item_id": opaque(),
                    "conversation_id": opaque(),
                    "subject": "当前用户",
                    "candidate": candidate,
                    "source": changed,
                }
                controls.append(control)
                control_truth.append(
                    {
                        "item_id": control["item_id"],
                        "base_item_id": item["item_id"],
                        "control": mode,
                        "expected": expected,
                        "original": label,
                    }
                )
        definitions_q = [
            (CATEGORIES[0], "一月时用户的常住城市是什么？", old, [old_id]),
            (CATEGORIES[1], "三月更新后用户的常住城市是什么？", new, [new_id]),
            (
                CATEGORIES[2],
                "结合三月两次会话，用户现在住在哪个城市、长期喜欢什么饮品？",
                f"{new}、{drink}",
                [new_id, drink_id],
            ),
        ]
        for cat, question, answer, relevant in definitions_q:
            queries.append(
                {
                    "question_id": opaque(),
                    "conversation_id": cid,
                    "category": cat,
                    "text": question,
                    "answer": answer,
                    "relevant": {k: 1 for k in relevant},
                    "evidence_level": "turn",
                    "source": "synthetic-hard-v1",
                    "synthetic": True,
                    "reference_status": STATUS,
                    "human_reviewed": False,
                }
            )
    rng.shuffle(items)
    rng.shuffle(controls)
    rng.shuffle(queries)
    ids = sorted(c["conversation_id"] for c in contexts)
    rng.shuffle(ids)
    split = {"dev": ids[: len(ids) * 3 // 10], "test": ids[len(ids) * 3 // 10 :]}
    write("contexts.jsonl", contexts)
    write("items.jsonl", items)
    write("constructor-truth-private.jsonl", truth)
    write("controls.jsonl", controls)
    write("control-truth-private.jsonl", control_truth)
    write("queries-proposed.jsonl", queries)
    (output / "split-proposed.json").write_text(json.dumps(split, sort_keys=True))
    # Stratified proposal only: owner columns intentionally blank; truth is separate.
    review = []
    by_id = {x["item_id"]: x for x in items}
    for kind in sorted({r["kind"] for r in truth}):
        pool = [r for r in truth if r["kind"] == kind]
        for t in rng.sample(pool, min(30, len(pool))):
            review.append({**by_id[t["item_id"]], "human_label": "", "human_reason": ""})
    rng.shuffle(review)
    write("owner-audit-proposed.jsonl", review)
    labels = {r["item_id"]: r["label"] for r in truth}
    strata = Counter(
        (labels[x["item_id"]], len(x["source"]), sum(len(d["text"]) for d in x["source"]))
        for x in items
    )
    manifest = {
        "name": "synthetic-hard-v1",
        "seed": seed,
        "conversations": count,
        "candidates": len(items),
        "queries": len(queries),
        "categories": dict(Counter(q["category"] for q in queries)),
        "controls": len(controls),
        "control_counts": dict(Counter(x["control"] for x in control_truth)),
        "expected_counterfactual_flips": sum(
            x["expected"] != x["original"]
            for x in control_truth
            if x["control"] == "counterfactual"
        ),
        "label_counts": dict(Counter(labels.values())),
        "source_length_label_strata": [
            {"label": l, "documents": n, "characters": c, "count": v}
            for (l, n, c), v in sorted(strata.items())
        ],
        "owner_audit_proposed": len(review),
        "model_annotations": 0,
        "model_control_runs": 0,
        "owner_annotations": 0,
        "quality_status": STATUS,
        "provenance": "independent locally program-constructed synthetic; no public corpus copied",
        "license": "no third-party dataset text; repository has no LICENSE; external redistribution license not established",
        "frozen_data_modified": False,
        "replacement_approved": False,
        "files": {p.name: file_hash(p) for p in sorted(output.iterdir()) if p.is_file()},
    }
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    # Hashes are deterministic across repeated runs with the same seed.
    manifest["artifact_digest"] = hashlib.sha256(
        json.dumps(manifest["files"], sort_keys=True).encode()
    ).hexdigest()
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return manifest


def propose_query_replacement(frozen: Path, hard: Path, output: Path) -> dict[str, Any]:
    """Materialize a reviewable next-version proposal, never change the frozen entry point."""
    if ".local" not in output.resolve().parts:
        raise ValueError("replacement proposal must stay private")
    output.mkdir(parents=True, exist_ok=False, mode=0o700)

    def read(path: Path) -> list[dict[str, Any]]:
        return [json.loads(line) for line in path.read_text().splitlines()]

    original = read(frozen / "queries.jsonl")
    selected_ids = sorted(r["conversation_id"] for r in read(hard / "contexts.jsonl"))[:250]
    proposed = [
        q for q in read(hard / "queries-proposed.jsonl") if q["conversation_id"] in selected_ids
    ]
    replaced = [q for q in original if q["category"] in CATEGORIES]
    if Counter(q["category"] for q in proposed) != Counter(q["category"] for q in replaced):
        raise ValueError("replacement must preserve counts by category")
    rows = [q for q in original if q["category"] not in CATEGORIES] + proposed
    contexts = {r["conversation_id"]: r for r in read(frozen / "contexts.jsonl")}
    contexts.update({r["conversation_id"]: r for r in read(hard / "contexts.jsonl")})
    needed = {q["conversation_id"] for q in rows}
    for name, records in [
        ("queries.jsonl", rows),
        ("contexts.jsonl", [contexts[k] for k in sorted(needed)]),
    ]:
        (output / name).write_text(
            "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in records)
        )
    split = json.loads((frozen / "split.json").read_text())
    hard_split = json.loads((hard / "split-proposed.json").read_text())
    next_split = {
        part: sorted(needed.intersection(ids + hard_split[part])) for part, ids in split.items()
    }
    if (
        set(next_split["dev"]) & set(next_split["test"])
        or set().union(*map(set, next_split.values())) != needed
    ):
        raise ValueError("replacement split overlap or missing conversations")
    (output / "split.json").write_text(json.dumps(next_split, sort_keys=True))
    result = {
        "approved": False,
        "activated": False,
        "status": STATUS,
        "queries": len(rows),
        "replaced": len(replaced),
        "categories": dict(Counter(q["category"] for q in rows)),
        "unchanged_other_queries": len(original) - len(replaced),
        "split_note": "new proposal inherits original other-source and independent hard-set conversation splits; this is not the frozen test set",
        "frozen_queries_sha256": file_hash(frozen / "queries.jsonl"),
        "files": {p.name: file_hash(p) for p in sorted(output.iterdir())},
    }
    (output / "manifest.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return result
