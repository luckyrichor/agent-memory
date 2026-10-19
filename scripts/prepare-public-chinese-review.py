"""DuLeMon-BOTH source conversations + explicit assistant-only negative derivatives.

Corpus-provided personas are candidates, not human-verified extraction gold.
"""

import argparse
import json
import math
import random
import zipfile
from pathlib import Path

from agent_memory.evals.datasets import Conversation, Document, conversation_split, file_hash

p = argparse.ArgumentParser()
p.add_argument("--archive", type=Path, required=True)
p.add_argument("--output", type=Path, required=True)
a = p.parse_args()
if ".local" not in a.output.resolve().parts:
    p.error("review data must remain ignored .local/")
a.output.mkdir(parents=True, exist_ok=False)
a.output.chmod(0o700)
with zipfile.ZipFile(a.archive) as z:
    rows = [
        json.loads(line)
        for line in z.read("DuLeMon/both/train.json").decode().splitlines()
        if line.strip()
    ]
indices = list(range(len(rows)))
random.Random(42).shuffle(indices)
corpus = []
items = []
positives = []
facts = 0
for idx in indices:
    row = rows[idx]
    cid = f"dulemon-both-train:{idx:04d}"
    docs = []
    for i, turn in enumerate(row["conversation"]):
        utterance = turn.split("\t", 1)[0]
        speaker, sep, text = utterance.partition(":")
        if not sep or speaker not in ["Usr", "Bot"]:
            raise ValueError("unrecognized original speaker")
        docs.append(
            Document(
                source_id=f"turn:{i}",
                session_id=cid,
                role="user" if speaker == "Usr" else "assistant",
                text=text.strip(),
            )
        )
    conv = Conversation(
        conversation_id=cid,
        documents=docs,
        questions=[],
        metadata={
            "source": "DuLeMon/both/train.json",
            "source_row": idx,
            "synthetic": False,
            "scope": "full original conversation, existing segmented text retained",
        },
    )
    positive = []
    for j, persona in enumerate(row["user_said_persona"]):
        _, sep, fact = persona.partition(":")
        if not sep:
            raise ValueError("unrecognized original persona")
        positive.append(
            {
                "item_id": f"{cid}:persona:{j}",
                "conversation_id": cid,
                "subject": "当前用户Usr",
                "source": [d.model_dump(mode="json") for d in docs],
                "candidate": "用户陈述：" + fact.strip(),
            }
        )
    if not positive:
        continue
    corpus.append(conv)
    items.extend(positive)
    positives.append(conv)
    facts += len(positive)
    if len(positives) >= 300 and facts >= 1500:
        break
negative_count = math.ceil(len(positives) * 3 / 7)
for conv in positives[:negative_count]:
    cid = conv.conversation_id + ":assistant-only"
    docs = [d for d in conv.documents if d.role == "assistant"]
    if not docs:
        raise ValueError("cannot create declared assistant-only negative")
    corpus.append(
        Conversation(
            conversation_id=cid,
            documents=docs,
            questions=[],
            metadata={
                "source_conversation_id": conv.conversation_id,
                "derived_negative": True,
                "scope": "assistant-only derivative, not a full original conversation",
            },
        )
    )
    items.append(
        {
            "item_id": cid + ":candidate:0",
            "conversation_id": cid,
            "subject": "当前用户Usr",
            "source": [d.model_dump(mode="json") for d in docs],
            "candidate": "用户长期喜欢红茶。",
        }
    )
(a.output / "corpus.jsonl").write_text("".join(c.model_dump_json() + "\n" for c in corpus))
(a.output / "items.jsonl").write_text(
    "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in items)
)
# Derivatives MUST share their source conversation's split.
split = conversation_split([c.conversation_id for c in positives])
for ids in split.values():
    ids.extend(
        c.conversation_id for c in corpus if c.metadata.get("source_conversation_id") in set(ids)
    )
(a.output / "split.json").write_text(json.dumps(split, indent=2))
manifest = {
    "name": "dulemon-both-review-v1",
    "source_archive_sha256": file_hash(a.archive),
    "seed": 42,
    "original_conversations": len(positives),
    "original_user_persona_candidates": facts,
    "derived_assistant_only_negatives": negative_count,
    "combined_conversations": len(corpus),
    "negative_derivative_ratio": negative_count / len(corpus),
    "items": len(items),
    "license": "parent repository Apache-2.0; archive no separate license",
    "human_confirmed": False,
    "model_labels_complete": False,
    "limits": "original segmented text; source personas are candidates; assistant-only derivatives are not natural full negative conversations",
    "files": {f.name: file_hash(f) for f in a.output.iterdir() if f.is_file()},
}
(a.output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
print(json.dumps({k: v for k, v in manifest.items() if k != "files"}, ensure_ascii=False))
