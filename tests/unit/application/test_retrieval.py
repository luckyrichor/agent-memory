from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from agent_memory.application.ports import MemoryRecord
from agent_memory.application.retrieval import MemoryRetriever, RetrievalQuery
from agent_memory.domain.enums import MemoryType, ScopeKind
from agent_memory.domain.errors import MemoryScopeForbidden
from agent_memory.domain.models import Memory, MemoryScope
from agent_memory.domain.principal import RequestPrincipal
from agent_memory.infrastructure.in_memory_retrieval import InMemoryCandidateProvider


@pytest.mark.asyncio
async def test_eval_adapter_fuses_current_version_filters_tenant_and_pages():
    tenant, user = uuid4(), uuid4()
    principal = RequestPrincipal(tenant, user, frozenset(), frozenset({"memory:read"}),
                                 frozenset({"project"}))
    records, embeddings = [], {}
    for tid, text in [(tenant,"compiler failure"), (tenant,"compiler repaired"),
                      (uuid4(), "compiler private")]:
        m,v = Memory.create(tenant_id=tid, memory_id=uuid4(), version_id=uuid4(),
            memory_type=MemoryType.SEMANTIC, scope=MemoryScope(ScopeKind.WORKSPACE,"project",None),
            owner_user_id=user, content=text, now=datetime.now(UTC))
        records.append(MemoryRecord(m,(v,)))
        embeddings[v.version_id] = ("fixture",tuple([1.0]+[0.0]*1023))
    service = MemoryRetriever(InMemoryCandidateProvider(records, embeddings))
    page = await service.search(RetrievalQuery("compiler", tuple([1.0]+[0.0]*1023), "fixture",
                                              workspace_id="project", limit=1), principal)
    assert len(page.items)==1 and page.next_offset==1
    assert page.channel_counts=={"lexical":2,"vector":2,"structured":2}
    second = await service.search(RetrievalQuery("compiler",workspace_id="project",limit=1,offset=1),
                                  principal)
    assert second.next_offset is None
    assert second.items[0].memory_id!=page.items[0].memory_id
    with pytest.raises(MemoryScopeForbidden):
        await service.search(RetrievalQuery("compiler",workspace_id="private"),principal)


@pytest.mark.parametrize("vector,model", [([0.0]*1024,"model"), ([1.0],"model"),
                                         ([float("inf")]*1024,"model"), ([1.0]*1024,None)])
def test_query_vectors_fail_closed(vector,model):
    with pytest.raises(ValueError):
        RetrievalQuery("query",tuple(vector),model)


class SpyProvider:
    """Wraps the in-memory adapter and records which version ids had their body requested."""

    def __init__(self, inner, drop=frozenset()):
        self.inner, self.drop, self.requested, self.evidence_requested = inner, drop, [], []

    async def candidates(self, query, principal):
        return await self.inner.candidates(query, principal)

    async def evidence(self, version_ids, principal, per_version):
        self.evidence_requested.append(list(version_ids))
        return await self.inner.evidence(version_ids, principal, per_version)

    async def contents(self, version_ids, principal):
        self.requested.append(list(version_ids))
        found = await self.inner.contents(version_ids, principal)
        return {k: v for k, v in found.items() if k not in self.drop}


def _corpus(count):
    tenant, user = uuid4(), uuid4()
    principal = RequestPrincipal(tenant, user, frozenset(), frozenset({"memory:read"}),
                                 frozenset({"project"}))
    records = []
    for index in range(count):
        m, v = Memory.create(tenant_id=tenant, memory_id=uuid4(), version_id=uuid4(),
            memory_type=MemoryType.SEMANTIC, scope=MemoryScope(ScopeKind.WORKSPACE, "project", None),
            owner_user_id=user, content=f"compiler note {index}", now=datetime.now(UTC))
        records.append(MemoryRecord(m, (v,)))
    return principal, records


@pytest.mark.asyncio
async def test_body_text_is_fetched_only_for_the_requested_page():
    principal, records = _corpus(12)
    spy = SpyProvider(InMemoryCandidateProvider(records, {}))
    page = await MemoryRetriever(spy).search(RetrievalQuery("compiler", limit=5), principal)
    assert len(page.items) == 5 and page.next_offset == 5
    assert len(spy.requested) == 1 and len(spy.requested[0]) == 5  # 12 candidates, 5 bodies
    assert {hit.version_id for hit in page.items} == set(spy.requested[0])
    assert all(hit.content.startswith("compiler note") for hit in page.items)


@pytest.mark.asyncio
async def test_two_stage_page_matches_single_stage_order_and_empty_page_skips_second_stage():
    principal, records = _corpus(7)
    spy = SpyProvider(InMemoryCandidateProvider(records, {}))
    retriever = MemoryRetriever(spy)
    seen = []
    for offset in (0, 3, 6):
        page = await retriever.search(RetrievalQuery("compiler", limit=3, offset=offset), principal)
        seen.extend(hit.memory_id for hit in page.items)
    assert len(seen) == 7 and len(set(seen)) == 7  # pages tile the fused ranking, no overlap
    before = len(spy.requested)
    empty = await retriever.search(RetrievalQuery("compiler", limit=3, offset=9), principal)
    assert empty.items == () and len(spy.requested) == before  # nothing to fetch


@pytest.mark.asyncio
async def test_hit_whose_body_cannot_be_read_is_dropped_not_returned_blank():
    principal, records = _corpus(3)
    gone = records[0].current_version.version_id
    spy = SpyProvider(InMemoryCandidateProvider(records, {}), drop={gone})
    page = await MemoryRetriever(spy).search(RetrievalQuery("compiler", limit=10), principal)
    assert gone not in {hit.version_id for hit in page.items} and len(page.items) == 2


def _ref(n, role="supports"):
    from agent_memory.application.retrieval import EvidenceRef

    return EvidenceRef(UUID(int=n), role, "tool.result", datetime(2026, 10, 1, tzinfo=UTC),
                       f"session-{n}", n)


@pytest.mark.asyncio
async def test_evidence_is_requested_for_the_page_versions_only():
    principal, records = _corpus(8)
    spy = SpyProvider(InMemoryCandidateProvider(records, {}))
    page = await MemoryRetriever(spy).search(RetrievalQuery("compiler", limit=3), principal)
    assert len(spy.evidence_requested) == 1
    assert spy.evidence_requested[0] == [hit.version_id for hit in page.items]  # 3 of 8, in order
    assert all(hit.evidence == () and hit.evidence_total == 0 for hit in page.items)


@pytest.mark.asyncio
async def test_more_than_five_references_are_capped_but_the_total_is_kept():
    principal, records = _corpus(3)
    target = records[0].current_version.version_id
    refs = tuple(_ref(n) for n in range(1, 9))  # 8 references on one version
    inner = InMemoryCandidateProvider(records, {}, evidence_by_version={target: refs})
    page = await MemoryRetriever(inner).search(RetrievalQuery("compiler", limit=10), principal)
    hit = next(h for h in page.items if h.version_id == target)
    assert len(hit.evidence) == 5 and hit.evidence_total == 8
    others = [h for h in page.items if h.version_id != target]
    assert others and all(h.evidence == () and h.evidence_total == 0 for h in others)


@pytest.mark.asyncio
async def test_hit_with_evidence_on_the_requested_page_carries_refs_in_order_and_total():
    principal, records = _corpus(2)
    target = records[0].current_version.version_id
    refs = (_ref(1, "triggered_by"), _ref(2, "supports"))
    inner = InMemoryCandidateProvider(records, {}, evidence_by_version={target: refs})
    page = await MemoryRetriever(inner).search(RetrievalQuery("compiler", limit=10), principal)
    hit = next(h for h in page.items if h.version_id == target)
    assert [r.role for r in hit.evidence] == ["triggered_by", "supports"]
    assert hit.evidence_total == 2


@pytest.mark.asyncio
async def test_empty_page_does_not_ask_for_evidence():
    principal, records = _corpus(2)
    spy = SpyProvider(InMemoryCandidateProvider(records, {}))
    empty = await MemoryRetriever(spy).search(
        RetrievalQuery("compiler", limit=3, offset=9), principal)
    assert empty.items == () and spy.evidence_requested == []
