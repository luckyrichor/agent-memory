"""Per-table role independence and evidence gates. Never query balances."""

import json
from pathlib import Path
from typing import Any

from agent_memory.evals.datasets import file_hash
from agent_memory.evals.judge_pool import Judge, rank_judges


def evidence(descriptor: dict[str, str]) -> dict[str, Any]:
    path = Path(descriptor["path"])
    if file_hash(path) != descriptor["sha256"]:
        raise ValueError("judge evidence missing or changed")
    value: dict[str, Any] = json.loads(path.read_text())
    return value


def load_table_pool(config: dict[str, Any], policy: dict[str, Any], table_kind: str) -> list[Judge]:
    roles = policy["tables"][table_kind]
    if config["table_kind"] != table_kind or config["roles"] != roles:
        raise ValueError("pool does not match this table's frozen roles")
    if config["policy_sha256"] != file_hash(Path(config["policy_path"])):
        raise ValueError("frozen table policy changed")
    if json.loads(Path(config["policy_path"]).read_text()) != policy:
        raise ValueError("pool policy mismatch")
    if config["judge_prompt_sha256"] != file_hash(Path("docs/evals/prompts/judge-v1.txt")):
        raise ValueError("judge prompt changed; preflight/calibration invalid")
    excluded = {roles["answer_vendor"], *roles["annotation_vendors"]}
    judges = []
    for row in config["candidates"]:
        if policy["judge_vendors"].get(row["provider"] + ":" + row["model"]) != row["vendor"]:
            raise ValueError("judge vendor does not match frozen registry")
        preflight = evidence(row["preflight"])
        actual = evidence(row["actual_call"])
        if (
            preflight.get("model") != row["model"]
            or preflight.get("preflight_pass") is not True
            or actual.get("model") != row["model"]
            or actual.get("provider") != row["provider"]
            or actual.get("pass") is not True
            or not actual.get("at")
        ):
            raise ValueError("successful preflight and actual judge call required")
        # All primary/backups need owner calibration before a formal table can run.
        calibration = evidence(row["calibration"]) if row.get("calibration") else {}
        if (
            calibration.get("human_calibration_passed") is not True
            or calibration.get("owner_reviewed_count", 0) < 300
            or not (calibration.get("kappa", -1) >= 0.7 or calibration.get("accuracy", -1) >= 0.9)
            or not calibration.get("reviewer")
            or calibration.get("model") != row["model"]
            or calibration.get("provider") != row["provider"]
            or calibration.get("prompt_sha256") != config["judge_prompt_sha256"]
        ):
            raise ValueError("owner calibration missing for primary or backup")
        judges.append(Judge(row["model"], row["vendor"], True, provider=row["provider"]))
    return rank_judges(judges, excluded)
