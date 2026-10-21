import pytest

from agent_memory.evals.verbatim_filter import check_candidate


def case(candidate, user, assistant=""):
    return {
        "candidate": "用户陈述：" + candidate,
        "source": [
            {"source_id": "u", "role": "user", "text": user},
            {"source_id": "a", "role": "assistant", "text": assistant},
        ],
    }


@pytest.mark.parametrize(
    "candidate,user,assistant",
    [
        ("我最喜欢火锅", "我吃了火锅。", ""),
        ("我喜欢拼乐高", "我正在拼乐高。", ""),
        ("我有轻度强迫症", "我有强迫症。", ""),
        ("我被诊断出强迫症", "我有强迫症。", ""),
        ("我每个周末去市场", "我每周去市场。", ""),
        ("我叫张某", "我今天休息。", "小张你好。"),
        ("我是医生", "我喜欢医生。", ""),
        ("我是医生", "我妈妈是医生。", ""),
        ("我喜欢火锅", "我不喜欢火锅。", ""),
        ("我喜欢火锅", "我喜欢火锅吗？", ""),
        ("我喜欢火锅", "我听说他喜欢火锅。", ""),
        ("我住北京", "我工作很忙。", "你住北京。"),
        ("我失业，整天坐在沙发上", "我失业了。", ""),
    ],
)
def test_unsupported_details_or_wrong_attribution_never_survive(candidate, user, assistant):
    assert check_candidate(case(candidate, user, assistant)).status == "uncertain"


def test_direct_user_evidence_and_each_conjunct_required():
    assert check_candidate(case("我最喜欢火锅", "我最喜欢火锅。")).status == "supported"
    assert check_candidate(case("我是医生", "我现在是一名医生。")).status == "supported"
    assert check_candidate(case("我住北京，我喜欢火锅", "我住北京。")).status == "uncertain"
    result = check_candidate(case("我住北京，我喜欢火锅", "我住北京。我喜欢火锅。"))
    assert result.status == "supported" and len(result.evidence) == 2
    assert all(r["role"] == "user" for r in result.evidence)


def test_date_and_event_cannot_be_collected_from_different_clauses():
    assert (
        check_candidate(case("我今年10月结婚", "我今年10月订婚，明年结婚。")).status == "uncertain"
    )
    assert check_candidate(case("我住在上海", "我住在北京，我在上海工作。")).status == "uncertain"


def test_reordered_explicit_details_are_not_forced_to_match_the_entire_sentence():
    result = check_candidate(
        case("我妈妈明天来看我", "明天我妈妈就要来看我了，不想让她看到我不好的样子。")
    )
    assert result.status == "supported"
