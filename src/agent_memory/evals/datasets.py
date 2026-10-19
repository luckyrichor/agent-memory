"""Public data normalization, preserving source IDs and evidence granularity.

No answer text is used to create retrieval documents. Missing evidence is explicit.
Raw inputs and normalized corpora stay outside Git.
"""

import ast
import hashlib
import json
import random
import re
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Document(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    source_id: str
    session_id: str
    role: Literal["user", "assistant", "source"]
    text: str
    occurred_at: str | None = None


class Question(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    question_id: str
    text: str
    answer: str
    category: str
    relevant: dict[str, int]
    abstention: bool = False
    evidence_available: bool = True


class Conversation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    conversation_id: str
    documents: list[Document]
    questions: list[Question]
    metadata: dict[str, Any] = Field(default_factory=dict)


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def longmemeval(path: Path) -> Iterator[Conversation]:
    rows = json.loads(path.read_text())
    for row in rows:
        # Group S and oracle copies by question ID; never split the two variants independently.
        cid = "lme:" + str(row["question_id"])
        docs = []
        for occurrence, (sid, date, turns) in enumerate(
            zip(
                row["haystack_session_ids"],
                row["haystack_dates"],
                row["haystack_sessions"],
                strict=True,
            )
        ):
            for i, turn in enumerate(turns):
                docs.append(
                    Document(
                        source_id=f"{sid}@{occurrence}:{i}",
                        session_id=str(sid),
                        role=turn["role"],
                        text=turn["content"],
                        occurred_at=date,
                    )
                )
        abstention = str(row["question_id"]).endswith("_abs")
        yield Conversation(
            conversation_id=cid,
            documents=docs,
            questions=[
                Question(
                    question_id=cid,
                    text=row["question"],
                    answer=str(row["answer"]),
                    category="abstention" if abstention else row["question_type"],
                    relevant={} if abstention else {str(s): 1 for s in row["answer_session_ids"]},
                    abstention=abstention,
                )
            ],
            metadata={"evidence_level": "session", "question_date": row["question_date"]},
        )


def locomo(path: Path) -> Iterator[Conversation]:
    for row in json.loads(path.read_text()):
        cid = "locomo:" + str(row["sample_id"])
        conv = row["conversation"]
        docs = []
        for sid, turns in conv.items():
            if not re.fullmatch(r"session_\d+", sid):
                continue
            for turn in turns:
                # Both are human participants, NOT an alternating assistant transcript.
                docs.append(
                    Document(
                        source_id=turn["dia_id"],
                        session_id=sid,
                        role="source",
                        text=turn["speaker"] + ": " + turn["text"],
                        occurred_at=conv.get(sid + "_date_time"),
                    )
                )
        questions: list[Question] = []
        known_ids = {doc.source_id for doc in docs}
        for i, qa in enumerate(row["qa"]):
            abstention = qa["category"] == 5
            evidence = qa.get("evidence", [])
            questions.append(
                Question(
                    question_id=f"{cid}:q{i}",
                    text=qa["question"],
                    answer=str(qa.get("answer", qa.get("adversarial_answer", ""))),
                    category=str(qa["category"]),
                    relevant={} if abstention else {s: 1 for s in evidence},
                    abstention=abstention,
                    evidence_available=abstention
                    or (bool(evidence) and all(s in known_ids for s in evidence)),
                )
            )
        yield Conversation(
            conversation_id=cid,
            documents=docs,
            questions=questions,
            metadata={"evidence_level": "turn", "participants": "two humans"},
        )


def perltqa(memory: Path, qa_path: Path) -> Iterator[Conversation]:
    qa_by_person = {
        name: data for row in json.loads(qa_path.read_text()) for name, data in row.items()
    }
    for row in json.loads(memory.read_text()):
        name = row["profile"]["Protagonist"]
        cid = "perltqa:" + name
        docs = [
            Document(
                source_id="profile:" + k,
                session_id="profile",
                role="source",
                text=f"{name} {k}: {v}",
            )
            for k, v in row["profile"].items()
        ]
        for section in ("social_relationship", "events", "dialogues"):
            for key, value in row[section].items():
                # Source records, not inferred conversations or fabricated speaker roles.
                docs.append(
                    Document(
                        source_id=key,
                        session_id=key,
                        role="source",
                        text=json.dumps(value, ensure_ascii=False),
                    )
                )
        questions: list[Question] = []
        for category, groups in qa_by_person.get(name, {}).items():
            all_qas = (
                groups if isinstance(groups, list) else [q for qs in groups.values() for q in qs]
            )
            for qa in all_qas:
                reference = qa["Reference Memory"]
                refs = (
                    ["profile:" + reference]
                    if category == "profile"
                    else ast.literal_eval(reference)
                )
                if not isinstance(refs, list) or not all(isinstance(s, str) for s in refs):
                    raise ValueError("unrecognized PerLTQA reference format")
                questions.append(
                    Question(
                        question_id=f"{cid}:q{len(questions)}",
                        text=qa["Question"],
                        answer=qa["Answer"],
                        category=category,
                        relevant={s: 1 for s in refs},
                    )
                )
        yield Conversation(
            conversation_id=cid,
            documents=docs,
            questions=questions,
            metadata={"evidence_level": "source_record"},
        )


def dulemon(path: Path) -> Iterator[Conversation]:
    with zipfile.ZipFile(path) as archive:
        for member in sorted(archive.namelist()):
            if not member.endswith(".json"):
                continue
            with archive.open(member) as stream:
                for line_no, line in enumerate(stream):
                    if not line.strip():
                        continue
                    row = json.loads(line)
                    cid = f"dulemon:{member}:{line_no}"
                    docs = []
                    persona_evidence: dict[str, list[str]] = {}
                    for i, turn in enumerate(row["conversation"]):
                        text, _, labels = turn.partition("\t")
                        speaker, _, utterance = text.partition(":")
                        source_id = f"turn:{i}"
                        docs.append(
                            Document(
                                source_id=source_id,
                                session_id=cid,
                                role="source",
                                text=speaker + ":" + utterance,
                            )
                        )
                        for label in labels.split(","):
                            if label.strip():
                                persona_evidence.setdefault(label.strip(), []).append(source_id)
                    # Preserve gold personas as metadata, never add them as retrieval documents.
                    yield Conversation(
                        conversation_id=cid,
                        documents=docs,
                        questions=[],
                        metadata={
                            "evidence_level": "turn",
                            "personas": {k: v for k, v in row.items() if k != "conversation"},
                            "persona_evidence": persona_evidence,
                            "source_split": member,
                        },
                    )


def conversation_split(ids: list[str], *, seed: int = 42) -> dict[str, list[str]]:
    if len(set(ids)) != len(ids) or len(ids) < 2:
        raise ValueError("split needs >=2 unique conversation IDs")
    ordered = sorted(ids)
    random.Random(seed).shuffle(ordered)
    # Nearest integer, half rounded upwards; no per-question randomization.
    count = int(len(ordered) * 0.3 + 0.5)
    count = min(len(ordered) - 1, max(1, count))
    return {"dev": sorted(ordered[:count]), "test": sorted(ordered[count:])}


def validate_evidence(conv: Conversation) -> list[str]:
    ids = [d.source_id for d in conv.documents]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate source document ID")
    valid = set(ids)
    if conv.metadata.get("evidence_level") == "session":
        valid = {d.session_id for d in conv.documents}
    return sorted({ref for q in conv.questions for ref in q.relevant if ref not in valid})
