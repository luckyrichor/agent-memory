"""Reproducible source preparation, never assistant-supplied human gold.

All text stays in ignored local files. Corpus references are kept separate from
model inputs. Previously frozen conversation splits are append-only.
"""

import hashlib
import json
import random
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any

from agent_memory.evals.datasets import conversation_split, file_hash
from agent_memory.evals.labeling import load_labels

SEED = 42
MODELS = ("deepseek-v4-pro-0813", "minimax-m2.7")
CATEGORIES = ("归属错误", "无长期价值", "两个模型分歧", "候选表述不通顺", "其他")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    path.chmod(0o600)


def unsegment(text: str) -> str:
    """Remove segmentation ASCII spaces, no paraphrasing; retain original archive.

    This cannot recover original English word boundaries and does not claim to.
    """
    return text.replace(" ", "").strip()


def frozen_extension(
    old: dict[str, list[str]], additions: list[str], *, seed: int = SEED
) -> dict[str, list[str]]:
    old_ids = old["dev"] + old["test"]
    if len(old_ids) != len(set(old_ids)) or set(additions) & set(old_ids):
        raise ValueError("split overlap or duplicate frozen ID")
    extra = conversation_split(additions, seed=seed)
    return {name: old[name] + extra[name] for name in ("dev", "test")}


def inherit_source_split(
    frozen: dict[str, list[str]], aliases: dict[str, str]
) -> dict[str, list[str]]:
    """New annotations of existing corpus conversations inherit their frozen side."""
    mapping = {key: side for side, keys in frozen.items() for key in keys}
    if len(mapping) != sum(map(len, frozen.values())):
        raise ValueError("frozen source split overlaps")
    if len(set(aliases.values())) != len(aliases):
        raise ValueError("duplicate source conversation alias")
    if not set(aliases.values()) <= mapping.keys():
        raise ValueError("source conversation missing from frozen split")
    return {
        side: sorted(key for key, source in aliases.items() if mapping[source] == side)
        for side in ("dev", "test")
    }


def diagnose(items: Path, left: Path, right: Path) -> dict[str, Any]:
    """Disjoint reason-code attribution, not a new human adjudication.

    Label disagreement takes precedence over reasons. No model reason code
    measures fluency: absence of that code is explicitly unassessed, not proof
    that there are zero disfluent candidates.
    """
    rows = read_jsonl(items)
    a, b = load_labels(left), load_labels(right)
    ids = [str(row["item_id"]) for row in rows]
    if len(ids) != len(set(ids)) or set(ids) != a.keys() or a.keys() != b.keys():
        raise ValueError("diagnostic coverage mismatch")
    buckets: dict[str, list[str]] = {name: [] for name in CATEGORIES}
    reasons: Counter[str] = Counter()
    for row in rows:
        key = str(row["item_id"])
        x, y = a[key], b[key]
        if x.label == y.label == "keep":
            continue
        if x.label != y.label or "uncertain" in (x.label, y.label):
            category = "两个模型分歧"
        elif "attribution" in (x.reason, y.reason):
            category = "归属错误"
        elif "temporary" in (x.reason, y.reason):
            category = "无长期价值"
        else:
            category = "其他"
        buckets[category].append(key)
        reasons[x.reason + "/" + y.reason] += 1
    return {
        "candidate_count": len(rows),
        "joint_keep": sum(a[k].label == b[k].label == "keep" for k in ids),
        "not_joint_keep": sum(map(len, buckets.values())),
        "categories": {
            name: {"count": len(keys), "example_ids": keys[:3]} for name, keys in buckets.items()
        },
        "reason_pairs": dict(sorted(reasons.items())),
        "fluency_assessed": False,
        "category_basis": "Existing model reasons only, disagreement first; not human truth.",
        "decision": "Source/evidence mismatch dominates; keep semantic annotation guide unchanged.",
        "input_sha256": {
            "items": file_hash(items),
            "left": file_hash(left),
            "right": file_hash(right),
        },
    }


def dulemon(
    archive: Path, old_items: Path, output: Path, *, count: int = 400, seed: int = SEED
) -> dict[str, Any]:
    with zipfile.ZipFile(archive) as z:
        rows = [json.loads(s) for s in z.read("DuLeMon/both/train.json").decode().splitlines() if s]
    used = {
        int(str(r["conversation_id"]).split(":")[1])
        for r in read_jsonl(old_items)
        if ":assistant-only" not in str(r["conversation_id"])
    }
    pool = sorted(set(range(len(rows))) - used)
    random.Random(seed).shuffle(pool)
    chosen = pool[:count]
    if len(chosen) != count:
        raise ValueError("not enough unused DuLeMon conversations")
    items, references, corpus = [], [], []
    for index in chosen:
        row = rows[index]
        cid = f"dulemon-both-train:{index:04d}"
        source = []
        for turn_no, turn in enumerate(row["conversation"]):
            utterance, _, _annotations = turn.partition("\t")
            speaker, sep, text = utterance.partition(":")
            if not sep or speaker not in ("Usr", "Bot"):
                raise ValueError("unknown DuLeMon speaker")
            source.append(
                {
                    "source_id": f"turn:{turn_no}",
                    "session_id": cid,
                    "role": "user" if speaker == "Usr" else "assistant",
                    "text": unsegment(text),
                }
            )
        corpus.append({"conversation_id": cid, "source": source})
        for field, label in (("user_said_persona", "keep"), ("user_no_said_persona", "discard")):
            for number, persona in enumerate(row[field]):
                _, sep, fact = persona.partition(":")
                if not sep:
                    raise ValueError("unknown persona syntax")
                # Opaque IDs: never expose said/no-said reference names to models.
                opaque = hashlib.sha256(f"{field}:{number}".encode()).hexdigest()[:16]
                key = f"{cid}:candidate:{opaque}"
                items.append(
                    {
                        "item_id": key,
                        "conversation_id": cid,
                        "subject": "当前用户Usr",
                        "source": source,
                        "candidate": "用户陈述：" + unsegment(fact),
                    }
                )
                references.append({"item_id": key, "label": label, "reason": "corpus:" + field})
    output.mkdir(parents=True, exist_ok=False)
    output.chmod(0o700)
    items.sort(key=lambda r: str(r["item_id"]))
    write_jsonl(output / "items.jsonl", items)
    write_jsonl(output / "references.jsonl", references)
    write_jsonl(output / "corpus.jsonl", corpus)
    result = {
        "source": "DuLeMon/both/train.json",
        "source_archive_sha256": file_hash(archive),
        "source_url": "https://dialogue.bj.bcebos.com/Knover/DuLeMon.zip",
        "license": "parent Apache-2.0; no separate archive license",
        "seed": seed,
        "source_origin": "human persona-conditioned dialogue, not production logs",
        "previously_used_indices": sorted(used),
        "new_indices": chosen,
        "overlap": len(used & set(chosen)),
        "conversations": len(corpus),
        "candidates": len(items),
        "reference_keep": sum(r["label"] == "keep" for r in references),
        "reference_discard": sum(r["label"] == "discard" for r in references),
        "reference_negative_conversations": sum(not rows[i]["user_said_persona"] for i in chosen),
        "synthetic": False,
        "corpus_reference_not_human_approved": True,
        "transformation": "ASCII segmentation spaces removed; archive retained; no paraphrasing",
    }
    return result


def perltqa(memory: Path, qa: Path, output: Path) -> dict[str, Any]:
    """Use native memory records, no model filtering and no fabricated binary negatives."""
    profiles = json.loads(memory.read_text())
    items, references = [], []
    dialogues = 0
    sections: Counter[str] = Counter()
    for profile in profiles:
        name = profile["profile"]["Protagonist"]
        group = "perltqa:" + name
        for section in ("profile", "social_relationship", "events", "dialogues"):
            for key, record in profile[section].items():
                sections[section] += 1
                dialogues += section == "dialogues"
                item_id = f"{group}:{section}:{key}"
                text = record if isinstance(record, str) else json.dumps(record, ensure_ascii=False)
                items.append(
                    {
                        "item_id": item_id,
                        "conversation_id": group,
                        "subject": name,
                        "candidate": f"{section}/{key}: {text}",
                        "source": [{"role": "source", "source_id": item_id, "text": text}],
                    }
                )
                references.append(
                    {"item_id": item_id, "label": "keep", "reason": "corpus:native-memory"}
                )
    output.mkdir(parents=True, exist_ok=False)
    output.chmod(0o700)
    write_jsonl(output / "items.jsonl", items)
    write_jsonl(output / "references.jsonl", references)
    (output / "split.json").write_text(
        json.dumps(
            conversation_split(["perltqa:" + p["profile"]["Protagonist"] for p in profiles]),
            indent=2,
        )
    )
    return {
        "source_url": "https://github.com/Elvin-Yiming-Du/PerLTQA",
        "license": "CC BY-NC 4.0",
        "license_url": "https://creativecommons.org/licenses/by-nc/4.0/",
        "paper": "https://aclanthology.org/2024.sighan-1.18/",
        "memory_sha256": file_hash(memory),
        "qa_sha256": file_hash(qa),
        "profile_groups": len(profiles),
        "conversations": dialogues,
        "native_memory_records": len(items),
        "sections": dict(sections),
        "reference_keep": len(items),
        "reference_discard": 0,
        "synthetic": True,
        "real_chinese_count_contribution": 0,
        "origin": "GPT-3.5-generated memory/dialogue, manually revised by original authors",
        "models": None,
        "joint_keep": None,
        "kappa": None,
        "limits": "Native memory records are not atomic, dialogue-grounded extraction facts. No invented negatives or new model-derived gold.",
    }


def ecd(archive: Path, output: Path, *, count: int = 400, seed: int = SEED) -> dict[str, Any]:
    if archive.stat().st_size != 54_000_633:
        raise ValueError("ECD archive size mismatch")
    chosen: dict[str, tuple[int, list[str]]] = {}
    seen = set()
    positive_rows = negative_rows = duplicates = malformed = 0
    rng = random.Random(seed)
    unique = 0
    # Reservoir sample unique positive contexts: negative response-ranking labels
    # are unrelated replies, not negative memories and not negative conversations.
    with zipfile.ZipFile(archive) as z:
        if z.testzip() is not None:
            raise ValueError("ECD ZIP CRC failure")
        with z.open("E-commerce dataset/train.txt") as stream:
            reservoir: list[tuple[str, int, list[str]]] = []
            for row_no, raw in enumerate(stream):
                fields = raw.decode("utf-8").rstrip("\r\n").split("\t")
                if len(fields) < 3 or fields[0] not in ("0", "1"):
                    malformed += 1
                    continue
                if fields[0] == "0":
                    negative_rows += 1
                    continue
                positive_rows += 1
                context = fields[1:-1]
                # Same history across candidate-response rows is one context.
                digest = hashlib.sha256(
                    json.dumps([unsegment(t) for t in context], ensure_ascii=False).encode()
                ).hexdigest()
                if digest in seen:
                    duplicates += 1
                    continue
                seen.add(digest)
                unique += 1
                entry = (digest, row_no, context + [fields[-1]])
                if len(reservoir) < count:
                    reservoir.append(entry)
                else:
                    replace = rng.randrange(unique)
                    if replace < count:
                        reservoir[replace] = entry
            chosen = {digest: (row_no, texts) for digest, row_no, texts in reservoir}
    if len(chosen) != count or malformed:
        raise ValueError("ECD source incomplete or malformed")
    items, corpus = [], []
    for digest, (row_no, texts) in sorted(chosen.items()):
        cid = "ecd:train:" + digest
        source = [
            {"source_id": f"turn:{i}", "session_id": cid, "role": "source", "text": unsegment(t)}
            for i, t in enumerate(texts)
        ]
        corpus.append({"conversation_id": cid, "source_row": row_no, "source": source})
        for i, turn in enumerate(source):
            items.append(
                {
                    "item_id": f"{cid}:utterance:{i}",
                    "conversation_id": cid,
                    "subject": "来源会话的客户；原件无说话人标签，不能凭轮次奇偶推断客户/客服归属",
                    "candidate": turn["text"],
                    "source": source,
                }
            )
    output.mkdir(parents=True, exist_ok=False)
    output.chmod(0o700)
    write_jsonl(output / "items.jsonl", items)
    write_jsonl(output / "corpus.jsonl", corpus)
    (output / "split.json").write_text(
        json.dumps(
            conversation_split([str(r["conversation_id"]) for r in corpus], seed=seed), indent=2
        )
    )
    return {
        "source_url": "https://drive.google.com/file/d/154J-neBo20ABtSmJDvm7DK0eTuieAuvw/view",
        "repository": "https://github.com/cooelf/DeepUtteranceAggregation",
        "paper": "https://arxiv.org/abs/1806.09102",
        "license": "unknown; local evaluation only",
        "archive_bytes": archive.stat().st_size,
        "archive_sha256": file_hash(archive),
        "zip_crc_passed": True,
        "member": "E-commerce dataset/train.txt",
        "positive_response_rows": positive_rows,
        "negative_response_rows": negative_rows,
        "unique_positive_contexts": unique,
        "duplicate_positive_contexts": duplicates,
        "malformed_rows": malformed,
        "seed": seed,
        "conversations": len(corpus),
        "candidates": len(items),
        "reference_labels": None,
        "sampled_context_hashes": sorted(chosen),
        "sampled_source_rows": sorted(v[0] for v in chosen.values()),
        "candidate_method": "All original utterances, no LLM prefilter or semantic rewriting",
        "speaker_roles_available": False,
        "synthetic": False,
        "transformation": "Remove ASCII segmentation spaces; retain ZIP, no speaker inference",
        "limits": "Response label 0 is not memory discard; anonymous roles may prevent customer attribution. All gold requires independent annotations and owner arbitration/audit.",
    }
