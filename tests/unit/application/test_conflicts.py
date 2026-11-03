"""E4: the structural conflict rule, without a database and without a budget."""
from uuid import UUID, uuid4

from agent_memory.application.conflicts import find_conflicts
from agent_memory.application.retrieval import RetrievalHit
from agent_memory.domain.enums import MemoryType


def hit(n: int, text: str, *, subject=None, memory_type=MemoryType.SEMANTIC,
        scope_kind="tenant") -> RetrievalHit:
    return RetrievalHit(UUID(int=n), UUID(int=n + 100), text, 1.0, {}, {},
                        memory_type=memory_type, scope_kind=scope_kind,
                        subject_id=subject)


SUBJECT = uuid4()


def test_restatements_of_one_fact_are_marked_both_ways():
    left = hit(1, "the rollout window for the billing service is Tuesday at nine",
               subject=SUBJECT)
    right = hit(2, "the rollout window for the billing service is Wednesday at nine",
                subject=SUBJECT)
    found = find_conflicts((left, right))
    assert found[left.memory_id] == (right.memory_id,)
    assert found[right.memory_id] == (left.memory_id,)


def test_a_different_subject_is_never_a_conflict():
    """Same wording, different person: two people can legitimately have different answers."""
    left = hit(1, "the rollout window for the billing service is Tuesday at nine",
               subject=uuid4())
    right = hit(2, "the rollout window for the billing service is Wednesday at nine",
                subject=uuid4())
    assert find_conflicts((left, right)) == {}


def test_a_different_memory_type_is_never_a_conflict():
    left = hit(1, "the rollout window for the billing service is Tuesday at nine",
               subject=SUBJECT, memory_type=MemoryType.SEMANTIC)
    right = hit(2, "the rollout window for the billing service is Wednesday at nine",
                subject=SUBJECT, memory_type=MemoryType.PROCEDURAL)
    assert find_conflicts((left, right)) == {}


def test_identical_text_is_left_to_dedup():
    """E2 merges identical content; calling it a conflict would be noise on every duplicate."""
    left = hit(1, "the rollout window is Tuesday at nine", subject=SUBJECT)
    right = hit(2, "the rollout window is Tuesday at nine", subject=SUBJECT)
    assert find_conflicts((left, right)) == {}


def test_unrelated_text_in_the_same_group_is_not_marked():
    left = hit(1, "the rollout window is Tuesday at nine", subject=SUBJECT)
    right = hit(2, "lunch is served in the cafeteria on Fridays", subject=SUBJECT)
    assert find_conflicts((left, right)) == {}


def test_short_texts_are_a_known_blind_spot():
    """Documented limit: token overlap cannot see "Beijing" vs "Shanghai" in a short sentence."""
    left = hit(1, "I live in Beijing", subject=SUBJECT)
    right = hit(2, "I moved to Shanghai", subject=SUBJECT)
    assert find_conflicts((left, right)) == {}


def test_the_threshold_moves_the_line():
    left = hit(1, "deploy the gateway to staging before the release freeze", subject=SUBJECT)
    right = hit(2, "deploy the gateway to production before the release freeze", subject=SUBJECT)
    assert find_conflicts((left, right), similarity=0.6)  # overlapping wording
    assert find_conflicts((left, right), similarity=0.95) == {}


def test_the_cap_keeps_the_most_similar_peers():
    base = "the rollout window for the billing service is Tuesday at nine o'clock"
    peers = [
        hit(1, base, subject=SUBJECT),
        hit(2, base.replace("nine", "ten"), subject=SUBJECT),      # one token differs
        hit(3, base.replace("nine", "eleven"), subject=SUBJECT),   # one token differs
        hit(4, base.replace("nine", "twelve") + " sharp", subject=SUBJECT),
    ]
    found = find_conflicts(peers, limit=1)
    assert found[UUID(int=1)] == (UUID(int=2),)  # deterministic: highest similarity, then id
    assert all(len(peers_for) == 1 for peers_for in found.values())


def test_an_empty_packet_costs_nothing():
    assert find_conflicts(()) == {}
    assert find_conflicts((hit(1, "only one memory here", subject=SUBJECT),)) == {}
