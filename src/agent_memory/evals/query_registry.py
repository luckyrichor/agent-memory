"""Resolve approved query versions without overwriting frozen datasets."""

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from agent_memory.evals.datasets import Conversation, Document, Question, file_hash


def materialize_active_queries(registry: Path, output: Path) -> dict[str, Any]:
    config = json.loads(registry.read_text())
    if config.get("active") is not True or config.get("owner_approved") is not True:
        raise ValueError("owner-approved active query version required")
    if ".local" not in output.resolve().parts:
        raise ValueError("private dataset output required")
    files = config["files"]
    for row in files.values():
        if file_hash(Path(row["path"])) != row["sha256"]:
            raise ValueError("active query hash changed")

    def read(name: str) -> list[dict[str, Any]]:
        return [json.loads(s) for s in Path(files[name]["path"]).read_text().splitlines()]

    contexts = {x["conversation_id"]: x for x in read("contexts")}
    questions = read("queries")
    grouped: dict[str, list[Question]] = defaultdict(list)
    levels: dict[str, dict[str, str]] = defaultdict(dict)
    ids = set()
    for row in questions:
        qid, cid = row["question_id"], row["conversation_id"]
        if qid in ids or cid not in contexts:
            raise ValueError("question coverage invalid")
        ids.add(qid)
        valid = {d["source_id"] for d in contexts[cid]["documents"]} | {
            d["session_id"] for d in contexts[cid]["documents"]
        }
        if not set(row["relevant"]) <= valid:
            raise ValueError("query evidence absent from source")
        grouped[cid].append(
            Question.model_validate({k: v for k, v in row.items() if k in Question.model_fields})
        )
        levels[cid][qid] = row.get("evidence_level", "source-record")
    corpus = [
        Conversation(
            conversation_id=cid,
            documents=[Document.model_validate(d) for d in contexts[cid]["documents"]],
            questions=grouped[cid],
            metadata={
                "query_version": config["version"],
                "evidence_level_by_question": levels[cid],
                "flow_only_categories": config["flow_only_categories"],
                "quality_status": "mixed-source; flow-only categories excluded from quality evidence",
            },
        )
        for cid in sorted(grouped)
    ]
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x") as stream:
        for conv in corpus:
            stream.write(conv.model_dump_json() + "\n")
    return {
        "version": config["version"],
        "conversations": len(corpus),
        "queries": len(questions),
        "sha256": file_hash(output),
        "flow_only_categories": config["flow_only_categories"],
    }
