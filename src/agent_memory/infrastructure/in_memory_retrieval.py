"""Small evaluation adapter; lexical tokens emulate 'simple', not PostgreSQL itself."""

import math
from dataclasses import dataclass
from uuid import UUID

from agent_memory.application.ports import MemoryRecord
from agent_memory.application.retrieval import Candidate, RetrievalQuery
from agent_memory.domain.enums import MemoryStatus
from agent_memory.domain.lexical import lexical_tokens
from agent_memory.domain.principal import RequestPrincipal


@dataclass
class InMemoryCandidateProvider:
    records: list[MemoryRecord]
    embeddings: dict[UUID, tuple[str, tuple[float, ...]]]

    async def candidates(
        self, query: RetrievalQuery, principal: RequestPrincipal
    ) -> list[Candidate]:
        channels: dict[str, list[Candidate]] = {"lexical": [], "vector": [], "structured": []}
        tokens = lexical_tokens(query.text)
        for record in self.records:
            m, v = record.memory, record.current_version
            if m.tenant_id != principal.tenant_id or m.status is not MemoryStatus.ACTIVE:
                continue
            if m.scope.workspace_id and not principal.can_access_workspace(m.scope.workspace_id):
                continue
            if (
                m.scope.subject_user_id
                and m.scope.subject_user_id != principal.user_id
                and "memory:admin" not in principal.permissions
            ):
                continue
            if query.workspace_id and m.scope.workspace_id not in (None, query.workspace_id):
                continue
            if query.memory_type and m.memory_type != query.memory_type:
                continue
            content_tokens = lexical_tokens(v.content)
            if tokens and tokens <= content_tokens:
                channels["lexical"].append(
                    Candidate(m.memory_id, v.version_id, v.content, "lexical", len(tokens))
                )
            embedding = self.embeddings.get(v.version_id)
            if query.vector and embedding and embedding[0] == query.model:
                vector = embedding[1]
                norm = math.sqrt(sum(x * x for x in vector) * sum(x * x for x in query.vector))
                if norm > 0:
                    score = sum(a * b for a, b in zip(vector, query.vector, strict=True)) / norm
                    channels["vector"].append(
                        Candidate(m.memory_id, v.version_id, v.content, "vector", score)
                    )
            if query.memory_type or query.workspace_id:
                channels["structured"].append(
                    Candidate(m.memory_id, v.version_id, v.content, "structured", 1)
                )
        return [
            c
            for channel in channels.values()
            for c in sorted(channel, key=lambda c: (-c.raw_score, str(c.memory_id)))[:1000]
        ]
