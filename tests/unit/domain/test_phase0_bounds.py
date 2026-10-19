from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from agent_memory.api.event_schemas import EventRequest
from agent_memory.api.schemas import SearchRequest
from agent_memory.domain.enums import ScopeKind
from agent_memory.domain.errors import InvalidEvent
from agent_memory.domain.events import EventDraft, EventType
from agent_memory.domain.models import MemoryScope


@pytest.mark.parametrize('payload', [
    {'role':'system', 'summary':'fixture'}, {'role':'user', 'summary':'x'*4001},
    {'tool_name':'build', 'exit_code':1, 'summary':'fixture'},
])
def test_conversation_payload_is_typed_and_bounded(payload):
    with pytest.raises(ValidationError):
        EventRequest.model_validate({'idempotency_key':'fixture','session_id':'fixture',
            'sequence_number':1,'event_type':'conversation.message','agent_id':'fixture',
            'occurred_at':'2026-10-18T00:00:00Z','scope':{'kind':'tenant'},'payload':payload})


def test_deep_domain_payload_rejected_without_recursion_error():
    value = {}
    for _ in range(2000):
        value = {'nested':value}
    with pytest.raises(InvalidEvent, match='depth'):
        EventDraft('key','session',1,EventType.TOOL_RESULT,'fixture', datetime.now(UTC),
                   MemoryScope(ScopeKind.TENANT,None,None),value)


@pytest.mark.parametrize('arguments', [{'query':'x'*2001}, {'query':'x','offset':2901},
                                      {'query':'x','limit':101}])
def test_existing_search_bounds_remain_enforced(arguments):
    with pytest.raises(ValidationError):
        SearchRequest(**arguments)
