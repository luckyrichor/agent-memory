import re
from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import String, and_, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from agent_memory.application.retrieval import Candidate, RetrievalQuery
from agent_memory.domain.principal import RequestPrincipal
from agent_memory.infrastructure.orm import MemoryEmbeddingRow, MemoryRow, MemoryVersionRow


class PostgresCandidateProvider:
    """Filter before ranking; only active current versions can enter any channel."""

    def __init__(self, session: AsyncSession, candidate_limit: int = 1000) -> None:
        self.session = session
        self.candidate_limit = candidate_limit

    async def contents(
        self, version_ids: Sequence[UUID], principal: RequestPrincipal
    ) -> dict[UUID, str]:
        """Second retrieval stage: bodies for the ids the channels already authorized."""
        if not version_ids:
            return {}
        v = MemoryVersionRow
        rows = await self.session.execute(
            select(v.memory_version_id, v.content).where(
                v.tenant_id == principal.tenant_id, v.memory_version_id.in_(list(version_ids))
            )
        )
        return {version_id: content for version_id, content in rows}

    async def candidates(
        self, query: RetrievalQuery, principal: RequestPrincipal
    ) -> list[Candidate]:
        m, v, e = MemoryRow, MemoryVersionRow, MemoryEmbeddingRow
        subject = or_(m.subject_user_id.is_(None), m.subject_user_id == principal.user_id)
        if "memory:admin" in principal.permissions:
            subject = or_(subject, m.subject_user_id.is_not(None))
        filters = [
            m.tenant_id == principal.tenant_id,
            m.status == "active",
            subject,
            or_(m.workspace_id.is_(None), m.workspace_id.in_(principal.allowed_workspace_ids)),
        ]
        if query.workspace_id is not None:
            filters.append(or_(m.workspace_id.is_(None), m.workspace_id == query.workspace_id))
        if query.memory_type is not None:
            filters.append(m.memory_type == query.memory_type.value)
        base = (
            select(m.memory_id, v.memory_version_id)
            .join(v, and_(v.tenant_id == m.tenant_id, v.memory_version_id == m.current_version_id))
            .where(*filters)
        )
        candidates: list[Candidate] = []
        if query.text.strip():
            chinese = bool(re.search(r"[一-鿿]", query.text))
            # Stored vectors (migration 0010): the per-row to_tsvector() used to dominate latency.
            document = v.lexical_zh if chinese else v.lexical_en
            # Tokenizer yields only CJK/ASCII word lexemes, never tsquery operators.
            # OR broadens Chinese paraphrases; PostgreSQL ranks overlap afterwards.
            terms = (
                func.to_tsquery(
                    "simple",
                    func.regexp_replace(
                        func.trim(func.memory_lexical_tokens(query.text)), r"\s+", " | ", "g"
                    ),
                )
                if chinese
                # Natural-language questions rarely occur verbatim in one turn.
                # Remove English stopwords/stem, then match any content lexeme.
                else func.to_tsquery(
                    "english",
                    func.replace(
                        cast(func.plainto_tsquery("english", query.text), String),
                        " & ",
                        " | ",
                    ),
                )
            )
            score = func.ts_rank_cd(document, terms)
            rows = await self.session.execute(
                base.add_columns(score)
                .where(document.op("@@")(terms))
                .order_by(score.desc(), m.memory_id)
                .limit(self.candidate_limit)
            )
            candidates.extend(
                Candidate(mid, vid, "lexical", float(raw)) for mid, vid, raw in rows
            )
        if query.vector is not None:
            distance = e.embedding.cosine_distance(list(query.vector))
            rows = await self.session.execute(
                base.join(
                    e, and_(e.tenant_id == m.tenant_id, e.memory_version_id == m.current_version_id)
                )
                .add_columns(distance)
                .where(e.model == query.model, distance <= 2)
                .order_by(distance, m.memory_id)
                .limit(self.candidate_limit)
            )
            candidates.extend(
                Candidate(mid, vid, "vector", 1 - float(raw)) for mid, vid, raw in rows
            )
        # Structured is opt-in; no broad unrelated candidates for an unfiltered query.
        if query.memory_type is not None or query.workspace_id is not None:
            rows = await self.session.execute(
                base.order_by(m.updated_at.desc(), m.memory_id).limit(self.candidate_limit)
            )
            candidates.extend(Candidate(mid, vid, "structured", 1) for mid, vid in rows)
        return candidates
