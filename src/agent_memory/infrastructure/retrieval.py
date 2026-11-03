import re
from collections.abc import Sequence
from typing import Literal
from uuid import UUID

from sqlalchemy import String, and_, cast, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from agent_memory.application.retrieval import Candidate, RetrievalQuery
from agent_memory.domain.principal import RequestPrincipal
from agent_memory.infrastructure.orm import MemoryEmbeddingRow, MemoryRow, MemoryVersionRow

# pgvector 0.8 added iterative index scans. Without them an approximate scan stops after
# ``hnsw.ef_search`` rows, so a tenant/status filter applied afterwards can leave the candidate
# list short (measured: 34 rows for a 1000-row limit at ef_search=40). The setting only exists on
# >= 0.8, which is why support is probed instead of assumed. Cached per process: the extension
# version cannot change while the process lives.
_ITERATIVE_SCAN: bool | None = None

VectorSearchMode = Literal["exact", "hnsw"]


async def iterative_scan_available(session: AsyncSession) -> bool:
    """Whether this server's pgvector can keep scanning until the LIMIT is satisfied."""
    global _ITERATIVE_SCAN
    if _ITERATIVE_SCAN is None:
        value = await session.scalar(text("SELECT current_setting('hnsw.iterative_scan', true)"))
        _ITERATIVE_SCAN = value is not None
    return _ITERATIVE_SCAN


class PostgresCandidateProvider:
    """Filter before ranking; only active current versions can enter any channel."""

    def __init__(
        self,
        session: AsyncSession,
        candidate_limit: int = 1000,
        *,
        vector_search: VectorSearchMode = "hnsw",
        ef_search: int = 100,
    ) -> None:
        self.session = session
        self.candidate_limit = candidate_limit
        self.vector_search = vector_search
        self.ef_search = ef_search

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
        m, v = MemoryRow, MemoryVersionRow
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
            candidates.extend(await self._vector_channel(query, principal, filters))
        # Structured is opt-in; no broad unrelated candidates for an unfiltered query.
        if query.memory_type is not None or query.workspace_id is not None:
            rows = await self.session.execute(
                base.order_by(m.updated_at.desc(), m.memory_id).limit(self.candidate_limit)
            )
            candidates.extend(Candidate(mid, vid, "structured", 1) for mid, vid in rows)
        return candidates

    async def _vector_channel(
        self,
        query: RetrievalQuery,
        principal: RequestPrincipal,
        filters: list[ColumnElement[bool]],
    ) -> list[Candidate]:
        """Nearest-first where it is safe (an HNSW index can serve it), exact scan otherwise.

        The nearest-first shape is the only one the planner can answer with an HNSW index: it
        orders by distance inside the embeddings table and joins the memory rows afterwards. The
        catch is that the tenant / status / scope filters are applied *after* the approximation,
        so on pgvector < 0.8 a filtered query can come back with far fewer rows than the limit.
        ``hnsw.iterative_scan`` removes that failure mode, which is why the shape is only used
        where the setting exists.
        """
        if self.vector_search == "hnsw" and await iterative_scan_available(self.session):
            return await self._nearest_first(query, principal, filters)
        return await self._exact_scan(query, filters)

    async def _nearest_first(
        self,
        query: RetrievalQuery,
        principal: RequestPrincipal,
        filters: list[ColumnElement[bool]],
    ) -> list[Candidate]:
        e, m, v = MemoryEmbeddingRow, MemoryRow, MemoryVersionRow
        # One round trip for both settings; they are transaction-local so they cannot leak into a
        # pooled connection's next request.
        await self.session.execute(
            text(
                "SELECT set_config('hnsw.ef_search', :ef, true),"
                " set_config('hnsw.iterative_scan', 'relaxed_order', true)"
            ),
            {"ef": str(self.ef_search)},
        )
        distance = e.embedding.cosine_distance(list(query.vector or ()))
        nearest = (
            select(e.memory_version_id.label("version_id"), distance.label("distance"))
            .where(e.tenant_id == principal.tenant_id, e.model == query.model)
            .order_by(distance)
            .limit(self.candidate_limit)
            .cte("nearest")
            .prefix_with("MATERIALIZED")
        )
        rows = await self.session.execute(
            select(m.memory_id, v.memory_version_id, nearest.c.distance)
            .join(nearest, nearest.c.version_id == m.current_version_id)
            .join(
                v,
                and_(v.tenant_id == m.tenant_id, v.memory_version_id == m.current_version_id),
            )
            .where(*filters)
            .order_by(nearest.c.distance, m.memory_id)
            .limit(self.candidate_limit)
        )
        return [
            Candidate(mid, vid, "vector", 1 - float(raw_distance))
            for mid, vid, raw_distance in rows
        ]

    async def _exact_scan(
        self, query: RetrievalQuery, filters: list[ColumnElement[bool]]
    ) -> list[Candidate]:
        e, m, v = MemoryEmbeddingRow, MemoryRow, MemoryVersionRow
        distance = e.embedding.cosine_distance(list(query.vector or ()))
        base = (
            select(m.memory_id, v.memory_version_id)
            .join(v, and_(v.tenant_id == m.tenant_id, v.memory_version_id == m.current_version_id))
            .where(*filters)
        )
        rows = await self.session.execute(
            base.join(
                e, and_(e.tenant_id == m.tenant_id, e.memory_version_id == m.current_version_id)
            )
            .add_columns(distance)
            .where(e.model == query.model, distance <= 2)
            .order_by(distance, m.memory_id)
            .limit(self.candidate_limit)
        )
        return [Candidate(mid, vid, "vector", 1 - float(raw)) for mid, vid, raw in rows]
