import re

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from agent_memory.application.retrieval import Candidate, RetrievalQuery
from agent_memory.domain.principal import RequestPrincipal
from agent_memory.infrastructure.orm import MemoryEmbeddingRow, MemoryRow, MemoryVersionRow


class PostgresCandidateProvider:
    """Filter before ranking; only active current versions can enter any channel."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

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
            select(m.memory_id, v.memory_version_id, v.content)
            .join(v, and_(v.tenant_id == m.tenant_id, v.memory_version_id == m.current_version_id))
            .where(*filters)
        )
        candidates: list[Candidate] = []
        if query.text.strip():
            chinese = bool(re.search(r"[一-鿿]", query.text))
            document = func.to_tsvector(
                "simple", func.memory_lexical_tokens(v.content) if chinese else v.content
            )
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
                else func.plainto_tsquery("simple", query.text)
            )
            score = func.ts_rank_cd(document, terms)
            rows = await self.session.execute(
                base.add_columns(score)
                .where(document.op("@@")(terms))
                .order_by(score.desc(), m.memory_id)
                .limit(1000)
            )
            candidates.extend(
                Candidate(mid, vid, content, "lexical", float(raw))
                for mid, vid, content, raw in rows
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
                .limit(1000)
            )
            candidates.extend(
                Candidate(mid, vid, content, "vector", 1 - float(raw))
                for mid, vid, content, raw in rows
            )
        # Structured is opt-in; no broad unrelated candidates for an unfiltered query.
        if query.memory_type is not None or query.workspace_id is not None:
            rows = await self.session.execute(
                base.order_by(m.updated_at.desc(), m.memory_id).limit(1000)
            )
            candidates.extend(
                Candidate(mid, vid, content, "structured", 1) for mid, vid, content in rows
            )
        return candidates
