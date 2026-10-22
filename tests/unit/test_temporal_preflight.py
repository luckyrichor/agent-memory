import json

from agent_memory.evals.annotate import shared_sources
from agent_memory.evals.temporal_preflight import virtual_item


def test_virtual_cases_remain_distinct_after_actual_wire_projection():
    wire = [json.dumps(shared_sources([virtual_item(i)]), sort_keys=True) for i in range(100)]
    assert len(set(wire)) == 100
    assert len({virtual_item(i)["candidate"] for i in range(100)}) == 100
    assert len({virtual_item(i)["source"][0]["text"] for i in range(100)}) == 100


def test_repeated_controls_have_identical_wire_payload_and_fresh_objects():
    first = virtual_item(0)
    second = virtual_item(0)
    assert shared_sources([first]) == shared_sources([second])
    first["source"][0]["text"] = "changed"
    assert second["source"][0]["text"] != "changed"
