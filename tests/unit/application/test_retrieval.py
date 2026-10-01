from datetime import UTC, datetime
from uuid import uuid4

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
