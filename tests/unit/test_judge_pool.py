import json

import pytest

from agent_memory.evals.judge_pool import (
    Grade,
    Judge,
    JudgeFailure,
    evaluate_table,
    judge_budget,
    rank_judges,
)


def test_quota_unknown_never_fabricates_order():
    with pytest.raises(ValueError, match="observed remaining"):
        rank_judges([Judge(str(i), "Tencent", True, None) for i in range(3)], {"Xiaomi"})
    ranked = rank_judges([Judge(str(i), "Tencent", True, 100 - i) for i in range(3)], {"Xiaomi"})
    assert [j.model for j in ranked] == ["0", "1", "2"]


@pytest.mark.asyncio
async def test_failover_regrades_entire_table_and_keeps_failed_ledger(tmp_path):
    calls = []

    async def request(judge, row):
        calls.append((judge.model, row["row_id"]))
        if judge.model == "a" and row["row_id"] == "2":
            raise JudgeFailure(402)
        return Grade(judge.model == "b", judge.model + "-version", "MATCH", {})

    out = tmp_path / ".local" / "table"
    result = await evaluate_table(
        "table",
        [{"row_id": str(i)} for i in range(3)],
        [Judge("a", "Tencent", True, 10), Judge("b", "Zhipu", True, 9)],
        request,
        out,
        retry_delay=0,
    )
    assert calls == [("a", "0"), ("a", "1"), ("a", "2"), ("b", "0"), ("b", "1"), ("b", "2")]
    assert result["discarded_previous_partial_scores"] == 2
    assert {r["judge"] for r in result["records"]} == {"b"}
    assert (out / "attempt-0.jsonl").exists()
    assert json.loads((out / "result.json").read_text())["complete"]


@pytest.mark.asyncio
async def test_all_failures_do_not_publish_partial_comparison(tmp_path):
    count = 0

    async def request(judge, row):
        nonlocal count
        count += 1
        raise JudgeFailure(500)

    out = tmp_path / ".local" / "table"
    with pytest.raises(JudgeFailure):
        await evaluate_table(
            "test", [{"row_id": "0"}], [Judge("a", "Tencent", True, 1)], request, out, retry_delay=0
        )
    assert count == 3
    assert not (out / "result.json").exists()


def test_section7_budget_separates_answer_and_judge():
    result = judge_budget(500, 4, 3)
    assert result["judge_calls"] == 6000
    assert result["combined_calls"] == 12000
    assert result["judge_total_tokens_estimate"] == 6600000


@pytest.mark.asyncio
async def test_returned_version_change_never_publishes_mixed_version(tmp_path):
    async def request(judge, row):
        return Grade(True, "version-" + row["row_id"], "MATCH", {})

    out = tmp_path / ".local" / "versions"
    with pytest.raises(JudgeFailure):
        await evaluate_table(
            "versions",
            [{"row_id": "1"}, {"row_id": "2"}],
            [Judge("a", "Tencent", True, 100)],
            request,
            out,
            retry_delay=0,
        )
    assert not (out / "result.json").exists()
