import copy
import json
from pathlib import Path

import pytest

from agent_memory.evals.datasets import file_hash
from agent_memory.evals.judge_pool import Grade, Judge, evaluate_table
from agent_memory.evals.table_pool import load_table_pool


def fixture(tmp_path):
    roles = {"answer_vendor": "ByteDance", "annotation_vendors": ["DeepSeek", "Tencent"]}
    policy = {
        "tables": {"synthetic-timeline": roles},
        "judge_vendors": {f"TokenHub:m{i}": "Xiaomi" for i in range(3)},
    }
    pp = tmp_path / "policy.json"
    pp.write_text(json.dumps(policy))
    prompt = file_hash(Path("docs/evals/prompts/judge-v1.txt"))

    def artifact(name, value):
        p = tmp_path / name
        p.write_text(json.dumps(value))
        return {"path": str(p), "sha256": file_hash(p)}

    config = {
        "table_kind": "synthetic-timeline",
        "roles": roles,
        "policy_path": str(pp),
        "policy_sha256": file_hash(pp),
        "judge_prompt_sha256": prompt,
        "candidates": [],
    }
    for i in range(3):
        model = f"m{i}"
        config["candidates"].append(
            {
                "model": model,
                "vendor": "Xiaomi",
                "provider": "TokenHub",
                "preflight": artifact(f"p{i}", {"model": model, "preflight_pass": True}),
                "actual_call": artifact(
                    f"a{i}", {"model": model, "provider": "TokenHub", "pass": True, "at": "fixture"}
                ),
                "calibration": artifact(
                    f"c{i}",
                    {
                        "model": model,
                        "provider": "TokenHub",
                        "human_calibration_passed": True,
                        "reviewer": "unit-fixture-only",
                        "owner_reviewed_count": 300,
                        "accuracy": 0.9,
                        "kappa": 0.5,
                        "prompt_sha256": prompt,
                    },
                ),
            }
        )
    return config, policy


def test_table_scoped_role_rules_do_not_union_unrelated_annotators(tmp_path):
    config, policy = fixture(tmp_path)
    assert [j.vendor for j in load_table_pool(config, policy, "synthetic-timeline")] == [
        "Xiaomi"
    ] * 3
    bad = copy.deepcopy(config)
    bad["roles"]["annotation_vendors"] = ["Zhipu"]
    with pytest.raises(ValueError, match="roles"):
        load_table_pool(bad, policy, "synthetic-timeline")


def test_uncalibrated_backup_or_changed_evidence_blocks_formal_run(tmp_path):
    config, policy = fixture(tmp_path)
    config["candidates"][2]["calibration"] = None
    with pytest.raises(ValueError, match="calibration"):
        load_table_pool(config, policy, "synthetic-timeline")
    p = Path(config["candidates"][0]["preflight"]["path"])
    p.write_text("{}")
    with pytest.raises(ValueError, match="changed"):
        load_table_pool(config, policy, "synthetic-timeline")


@pytest.mark.asyncio
async def test_explicit_synthetic_vendor_scope_allows_xiaomi_judge(tmp_path):
    async def request(judge, row):
        return Grade(True, "fixture-version", "MATCH", {})

    result = await evaluate_table(
        "fixture",
        [{"row_id": "a"}],
        [Judge("m", "Xiaomi", True)],
        request,
        tmp_path / ".local" / "result",
        excluded_vendors={"ByteDance", "DeepSeek", "Tencent"},
    )
    assert result["complete"]


def test_withdrawn_model_rejected_even_with_complete_old_evidence(tmp_path):
    config, policy = fixture(tmp_path)
    policy["withdrawn_judges"] = {"TokenHub:m0": "pre-offline"}
    path = Path(config["policy_path"])
    path.write_text(json.dumps(policy))
    config["policy_sha256"] = file_hash(path)
    with pytest.raises(ValueError, match="withdrawn"):
        load_table_pool(config, policy, "synthetic-timeline")
