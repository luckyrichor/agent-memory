"""Benchmark writes use the public SDK; source mappings are local eval artifacts.

Never silently truncate source text. Full mode accepts explicitly attributed turns
only. Opaque public records need a separately approved attribution mapping.
"""

import hashlib
from datetime import UTC, datetime
from typing import Any

from agent_memory.api.event_schemas import (
    ConversationPayloadRequest,
    EventBatchRequest,
    EventRequest,
)
from agent_memory.api.schemas import ScopeRequest, SearchRequest
from agent_memory.domain.enums import MemoryType
from agent_memory.domain.models import MemoryScope
from agent_memory.evals.datasets import Conversation
from agent_memory.sdk import MemoryClient


def key_for(*parts: str) -> str:
    return "eval:" + hashlib.sha256("\x00".join(parts).encode()).hexdigest()


def source_time(value: str | None) -> datetime:
    if value is None:
        raise ValueError("full import requires source time, never fabricate historical chronology")
    try:
        # LongMemEval timestamps have no offset; assumption is recorded by the caller.
        return datetime.strptime(value, "%Y/%m/%d (%a) %H:%M").replace(tzinfo=UTC)
    except ValueError:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            raise ValueError("source ISO timestamp must include timezone") from None
        return parsed


async def import_conversation(
    client: MemoryClient, conv: Conversation, scope: MemoryScope, *, mode: str
) -> list[dict[str, Any]]:
    if mode not in ("direct", "full"):
        raise ValueError("unknown import mode")
    if mode == "full" and any(d.role == "source" for d in conv.documents):
        raise ValueError("opaque source records lack user/assistant attribution for full mode")
    mapping = []
    sequence: dict[str, int] = {}
    for doc in conv.documents:
        # Preserve exact text by bounded pieces; all pieces point to the same evidence unit.
        for part, start in enumerate(range(0, len(doc.text), 4000)):
            chunk = doc.text[start : start + 4000]
            stable = key_for(
                conv.conversation_id,
                doc.source_id,
                mode,
                str(part),
                scope.kind.value,
                scope.workspace_id or "",
                str(scope.subject_user_id or ""),
            )
            row: dict[str, Any] = {
                "conversation_id": conv.conversation_id,
                "source_id": doc.source_id,
                "session_id": doc.session_id,
                "part": part,
                "content_sha256": hashlib.sha256(chunk.encode()).hexdigest(),
            }
            if mode == "direct":
                memory = await client.remember(
                    chunk, MemoryType.EPISODIC, scope, idempotency_key=stable
                )
                row.update(memory_id=str(memory.memory_id), version_id=str(memory.version_id))
            else:
                if doc.role not in ("user", "assistant"):
                    raise ValueError("unsupported source role")
                session = key_for(conv.conversation_id, doc.session_id)
                sequence[session] = sequence.get(session, 0) + 1
                event = EventRequest(
                    idempotency_key=stable,
                    session_id=session,
                    sequence_number=sequence[session],
                    event_type="conversation.message",
                    agent_id="benchmark-import-v1",
                    occurred_at=source_time(doc.occurred_at),
                    scope=ScopeRequest(
                        kind=scope.kind,
                        workspace_id=scope.workspace_id,
                        subject_user_id=scope.subject_user_id,
                    ),
                    payload=ConversationPayloadRequest(role=doc.role, summary=chunk),
                )
                ingested = await client.ingest_events(EventBatchRequest(events=[event]))
                row["event_id"] = str(ingested.items[0].event_id)
                # No generated memory IDs until workers run and evidence is observed.
            mapping.append(row)
    return mapping


async def retrieve_sources(
    client: MemoryClient,
    conv: Conversation,
    mapping: list[dict[str, Any]],
    *,
    workspace_id: str,
    k: int = 10,
) -> list[dict[str, Any]]:
    source_key = "session_id" if conv.metadata.get("evidence_level") == "session" else "source_id"
    versions: dict[str, set[str]] = {}
    for row in mapping:
        if "version_id" in row:
            versions.setdefault(row["version_id"], set()).add(row[source_key])
    if mapping and not versions:
        raise ValueError("full mode needs observed event-to-version evidence mapping after workers")
    results = []
    for q in conv.questions:
        response = await client.search(
            SearchRequest(query=q.text, workspace_id=workspace_id, limit=k)
        )
        ranked = []
        evidence_sets = []
        unmapped = 0
        for hit in response.items:
            sources = versions.get(str(hit.version_id))
            if sources is None:
                # Do not silently remove a false positive and improve Precision@k.
                sources = {"unmapped:" + str(hit.version_id)}
                unmapped += 1
            evidence_sets.append(sorted(sources))
            for source in sorted(sources):
                if source not in ranked:
                    ranked.append(source)
        results.append(
            {
                "question_id": q.question_id,
                "ranked_source_ids": ranked,
                "ranked_evidence_sets": evidence_sets,
                "ranked_memory_ids": [str(hit.memory_id) for hit in response.items],
                "vector_status": response.vector_status,
                "unmapped_hits": unmapped,
                "memory_results": len(response.items),
                "evidence_rank_collapse": True,
            }
        )
    return results
