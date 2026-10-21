"""Source-grounded Chinese queries; raw data stays private and approvals stay explicit."""

import json
import random
from collections import Counter
from pathlib import Path
from typing import Any

from agent_memory.evals.datasets import file_hash

CATEGORIES = (
    "single-session",
    "multi-session",
    "temporal-reasoning",
    "knowledge-update",
    "preference",
    "abstention",
)
PREFERENCES = {
    "喜欢": "喜好",
    "爱好": "爱好",
    "偏好": "偏好",
    "最爱": "喜好",
    "讨厌": "厌恶",
}


def records(path: Path) -> Any:
    with path.open() as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def build_queries(normalized: Path, timeline: Path, output: Path) -> dict[str, Any]:
    if ".local" not in output.resolve().parts:
        raise ValueError("queries, references and documents must remain private")
    output.mkdir(parents=True, exist_ok=False)
    output.chmod(0o700)
    rng = random.Random(42)
    buckets: dict[str, list[dict[str, Any]]] = {c: [] for c in CATEGORIES}
    contexts: dict[str, dict[str, Any]] = {}
    sources: list[Path] = []
    splits: dict[str, str] = {}
    for dataset in ("dulemon", "perltqa_zh"):
        path = normalized / f"{dataset}-split.json"
        sources.append(path)
        for part, ids in json.loads(path.read_text()).items():
            for cid in ids:
                splits[cid] = part
    for part, ids in json.loads((timeline / "split.json").read_text()).items():
        for cid in ids:
            splits[cid] = part
    sources.append(timeline / "split.json")

    perlt = normalized / "perltqa_zh.jsonl"
    sources.append(perlt)
    for conv in records(perlt):
        cid = conv["conversation_id"]
        contexts[cid] = conv
        for q in conv["questions"]:
            if len(q["relevant"]) != 1:
                continue  # only genuinely single-source questions enter this category
            buckets["single-session"].append(
                {
                    **q,
                    "category": "single-session",
                    "original_category": q["category"],
                    "conversation_id": cid,
                    "source": "PerLTQA-zh",
                    "synthetic": True,
                    "origin": "author-model-generated-public-benchmark",
                    "license": "CC-BY-NC-4.0",
                    "reference_status": "native-unreviewed",
                }
            )

    dulemon = normalized / "dulemon.jsonl"
    sources.append(dulemon)
    skipped_schema = 0
    for conv in records(dulemon):
        cid = conv["conversation_id"]
        personas = conv["metadata"]["personas"]
        if not {"user_said_persona", "user_no_said_persona"} <= personas.keys():
            skipped_schema += 1
            continue
        evidence = conv["metadata"]["persona_evidence"]
        preferred = []
        for persona in personas["user_said_persona"]:
            key, sep, fact = persona.partition(":")
            if not sep or not evidence.get(key):
                continue
            kinds = [v for k, v in PREFERENCES.items() if k in fact]
            if kinds:
                preferred.append((key, fact, kinds[0]))
        # Avoid asking one ambiguous question when several preferences are native-labeled.
        if len(preferred) == 1:
            key, fact, kind = preferred[0]
            contexts[cid] = conv
            buckets["preference"].append(
                {
                    "question_id": f"{cid}:query:preference:{key}",
                    "text": f"这段对话中，用户明确表达了什么{kind}？",
                    "answer": fact,
                    "relevant": {s: 1 for s in evidence[key]},
                    "category": "preference",
                    "conversation_id": cid,
                    "source": "DuLeMon",
                    "synthetic": False,
                    "license": "Apache-2.0-parent-repo",
                    "reference_status": "derived-from-native-unreviewed",
                    "abstention": False,
                }
            )
        for i, persona in enumerate(personas["user_no_said_persona"]):
            _, sep, fact = persona.partition(":")
            if not sep:
                raise ValueError("unexpected DuLeMon persona syntax")
            contexts[cid] = conv
            buckets["abstention"].append(
                {
                    "question_id": f"{cid}:query:abstention:{i}",
                    "text": f"只依据这段对话，能否确认用户的这项信息：{fact}？不能确认请明确拒答。",
                    "answer": "对话未提供足够依据，无法确认。",
                    "relevant": {},
                    "category": "abstention",
                    "conversation_id": cid,
                    "source": "DuLeMon",
                    "synthetic": False,
                    "license": "Apache-2.0-parent-repo",
                    "reference_status": "derived-from-native-unreviewed",
                    "abstention": True,
                }
            )

    path = timeline / "corpus.jsonl"
    sources.append(path)
    for conv in records(path):
        cid = conv["conversation_id"]
        contexts[cid] = conv
        for q in conv["questions"]:
            if q["category"] not in {"multi-session", "temporal-reasoning", "knowledge-update"}:
                continue
            buckets[q["category"]].append(
                {
                    **q,
                    "conversation_id": cid,
                    "source": "customer-timeline-v1",
                    "synthetic": True,
                    "license": "project-generated",
                    "reference_status": "流程验证，不作质量证据",
                }
            )
    chosen = []
    for cat in CATEGORIES:
        # 1000 native public benchmark questions plus 250 of every other type.
        target = 1000 if cat == "single-session" else 250
        candidates = sorted(buckets[cat], key=lambda r: r["question_id"])
        seen = set()
        unique = []
        for r in candidates:
            key = (r["conversation_id"], r["text"])
            if key not in seen:
                seen.add(key)
                unique.append(r)
        if len(unique) < target:
            raise ValueError(f"insufficient distinct queries in {cat}: {len(unique)} < {target}")
        chosen.extend(rng.sample(unique, target))
    chosen.sort(key=lambda r: r["question_id"])
    ids = {r["question_id"] for r in chosen}
    if len(ids) != len(chosen):
        raise ValueError("duplicate query IDs")
    used = {r["conversation_id"] for r in chosen}
    for row in chosen:
        row["split"] = splits[row["conversation_id"]]
        row["human_reviewed"] = False
        row["relevance_grades"] = "binary-native-only; graded relevance review pending"
        context = contexts[row["conversation_id"]]
        row["evidence_level"] = context["metadata"]["evidence_level"]
        field = "session_id" if row["evidence_level"] == "session" else "source_id"
        docs = {d[field] for d in context["documents"]}
        if set(row["relevant"]) - docs:
            raise ValueError("query reference does not map to frozen source documents")
    (output / "queries.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in chosen)
    )
    # Remove metadata/personas/questions from retrieval documents: no answers in index input.
    (output / "contexts.jsonl").write_text(
        "".join(
            json.dumps(
                {"conversation_id": cid, "documents": contexts[cid]["documents"]},
                ensure_ascii=False,
            )
            + "\n"
            for cid in sorted(used)
        )
    )
    (output / "split.json").write_text(
        json.dumps(
            {p: sorted(cid for cid in used if splits[cid] == p) for p in ("dev", "test")}, indent=2
        )
    )
    review = random.Random(42).sample(chosen, (len(chosen) + 9) // 10)
    (output / "query-audit-blind.jsonl").write_text(
        "".join(
            json.dumps({**r, "human_label": None, "human_reason": None}, ensure_ascii=False) + "\n"
            for r in review
        )
    )
    summary = {
        "dulemon_unsupported_schema_conversations": skipped_schema,
        "seed": 42,
        "queries": len(chosen),
        "conversations": len(used),
        "categories": dict(Counter(r["category"] for r in chosen)),
        "by_source": dict(Counter(r["source"] for r in chosen)),
        "by_source_category": {
            s: dict(Counter(r["category"] for r in chosen if r["source"] == s))
            for s in sorted({r["source"] for r in chosen})
        },
        "split_queries": dict(Counter(r["split"] for r in chosen)),
        "real_dialogue_derived_queries": sum(not r["synthetic"] for r in chosen),
        "public_benchmark_native_queries": sum(r["source"] == "PerLTQA-zh" for r in chosen),
        "constructed_timeline_queries": sum(r["source"] == "customer-timeline-v1" for r in chosen),
        "owner_confirmed_queries": 0,
        "query_audit_prepared": len(review),
        "query_audit_requested_now": False,
        "scale_target_pass": len(chosen) >= 1500
        and all(sum(r["category"] == cat for r in chosen) >= 150 for cat in CATEGORIES),
        "quality_gate_pass": False,
        "phase1_accepted": False,
        "split_policy": "inherit existing frozen conversation splits, no reassignment",
        "source_licenses": {
            "DuLeMon": {
                "url": "https://github.com/PaddlePaddle/Research/tree/master/NLP/ACL2022-DuLeMon",
                "license": "parent repository Apache-2.0; archive has no separate license",
            },
            "PerLTQA-zh": {
                "url": "https://github.com/Elvin-Yiming-Du/PerLTQA",
                "commit": "8d9e19868e239740ef701e603ec205cd581f221b",
                "license": "CC-BY-NC-4.0",
                "license_url": "https://creativecommons.org/licenses/by-nc/4.0/",
            },
            "customer-timeline-v1": {
                "generator": "scripts/prepare-timeline-review.py",
                "license": "project-generated; not human dialogue",
            },
        },
        "source_files": {str(p): file_hash(p) for p in sources},
        "files": {p.name: file_hash(p) for p in output.iterdir() if p.is_file()},
        "limitations": [
            "PerLTQA is author-model-generated, not real human dialogue",
            "native DuLeMon references and derived questions await owner verification",
            "timeline queries reuse old simple construction; flow only, not quality evidence",
            "only binary relevance available; no fabricated graded nDCG labels",
            "no system evaluated or tuned on held-out queries in this construction step",
        ],
    }
    (output / "manifest.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary
