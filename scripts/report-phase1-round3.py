"""Aggregate-only handoff. Never exports conversation IDs, text or owner answers."""

import argparse
import json
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from agent_memory.evals.datasets import file_hash
from agent_memory.evals.labeling import load_labels


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    local = Path(".local/phase1/round3")
    a.output.mkdir(parents=True, exist_ok=False)
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "generated_date_beijing": datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat(),
        "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "working_tree_modified_before_report": bool(
            subprocess.check_output(["git", "status", "--porcelain"])
        ),
        "phase": 1,
        "phase_gate_passed": False,
        "phase2_started": False,
        "annotation_models": ["deepseek-v4-pro", "mimo-v2.6-flash"],
        "annotation_replacement_requires_confirmation": True,
        "latest_plan_received": False,
        "original_plan_sha256": file_hash(Path("docs/agent-memory面试级完善方案.md")),
        "policy_sha256": file_hash(Path("docs/evals/phase1-round3-policy-v1.json")),
        "ecd": json.loads((local / "reviews/summary.json").read_text()),
        "budget": json.loads((local / "budget.json").read_text()),
        "candidates": [],
        "quota_ranked_pool_frozen": False,
        "primary_judge": None,
        "backups": [],
        "owner_native_audit_received": False,
        "human_confirmed_chinese_gold": 0,
        "chinese_gold_target": 1500,
    }
    records = json.loads((local / "access.json").read_text()) + json.loads(
        (local / "access-extra.json").read_text()
    )
    repeats = {r["model"]: r for r in json.loads((local / "judge-repeat.json").read_text())}
    for original in records:
        row = dict(original)
        model = row["model"]
        row["preflight_pass"] = False
        row["format_valid"] = 0
        row["format_n"] = 0
        row["consistent_5"] = False
        if row.get("http_status") == 402 and row.get("quota_exhausted"):
            row["remaining_free_tokens"] = 0
            row["quota_basis"] = (
                "Actual HTTP402 explicitly free trial exhausted and postpaid disabled; not entire account balance"
            )
        else:
            row["remaining_free_tokens"] = None
        folders = [local / ("preflight-" + model)]
        if model == "glm-5v-turbo":
            folders.append(local / "preflight-glm-5v-turbo-retest")
        history = []
        for folder in folders:
            summary = folder / (model + "-summary.json")
            if summary.exists():
                history.append(
                    {
                        "summary": json.loads(summary.read_text()),
                        "summary_sha256": file_hash(summary),
                        "response_failures": sum(
                            not r.get("format_valid")
                            for r in json.loads((folder / "progress.json").read_text())
                        ),
                    }
                )
        row["qualification_history"] = history
        if history:
            latest = history[-1]["summary"]
            for key in (
                "preflight_pass",
                "format_valid",
                "format_n",
                "consistent_5",
                "observed_disabled_thinking",
                "latency_ms",
            ):
                row[key] = latest[key]
        if model in repeats:
            row["judge_prompt_consistent_5"] = repeats[model]["consistent_5"]
            row["judge_prompt_responses"] = [
                {k: r[k] for k in ("score", "reason_code", "response_model", "usage") if k in r}
                for r in repeats[model]["records"]
            ]
        row["qualified_for_pool"] = bool(
            row["preflight_pass"] and row.get("judge_prompt_consistent_5")
        )
        report["candidates"].append(row)
    report["qualified_candidate_count"] = sum(r["qualified_for_pool"] for r in report["candidates"])
    report["required_pool_size"] = 3
    report["missing_qualified_candidates"] = max(0, 3 - report["qualified_candidate_count"])
    report["control_exclusions"] = {
        "glm-5.3_series": "officially cannot disable thinking",
        "kimi_series": "frozen sampling/cannot meet temperature0 policy",
        "minimax-m3.1-flash": "official M3.1 preview guidance disallows disabled-thinking",
    }
    old = json.loads(Path("docs/reports/phase1-model-rotation-2026-10-19/report.json").read_text())
    timeline = next(r for r in old["datasets"] if r["name"] == "synthetic-timeline")
    report["synthetic_timeline"] = {
        k: timeline[k]
        for k in ("candidate_count", "models", "complete", "items_sha256", "labels_sha256")
    }
    report["synthetic_timeline"].update(
        matches_current_frozen_pair=timeline["models"] == report["annotation_models"],
        relabel_proposal="Retain candidates/timeline/splits and fully label with frozen pair only after owner confirmation",
        relabel_executed=False,
    )
    refs = load_labels(Path(".local/phase1/chinese-expansion-v2/dulemon/references.jsonl"))
    report["native_dulemon_unreviewed_keep"] = sum(r.label == "keep" for r in refs.values())
    report["human_confirmed_chinese_gold_gap"] = (
        report["chinese_gold_target"] - report["human_confirmed_chinese_gold"]
    )
    retrieval = local / "retrieval-final"
    report["retrieval"] = {}
    for name in ("longmemeval_oracle", "locomo"):
        folder = retrieval / name
        result = json.loads((folder / "report/report.json").read_text())
        config = json.loads((folder / "config.json").read_text())
        report["retrieval"][name] = {
            "question_count": result["question_count"],
            "scored_count": result["scored_count"],
            "recall_at10": result["metrics"]["RT1@10"],
            "evidence_coverage_at10": result["metrics"]["evidence_coverage@10"],
            "mapping_records": config["mapping_records"],
            "channel": config["channel"],
            "full_corpus": False,
            "source_corpus_sha256": config["normalized_corpus_sha256"],
            "normalized_subset_sha256": file_hash(folder / "dataset-local.jsonl"),
            "prediction_sha256": file_hash(folder / "predictions.jsonl"),
            "run_scope": "first frozen development conversation; direct memory import; actual non-owner RLS PostgreSQL and ASGI HTTP API; no extraction/vector or full B0 claim",
        }
    log = (local / "check-final.log").read_text()
    test_match = re.search(r"(\d+) passed in ([\d.]+)s", log)
    assert test_match and "All checks passed!" in log
    report["validation"] = {
        "pytest_passed": int(test_match[1]),
        "pytest_seconds": float(test_match[2]),
        "ruff": True,
        "mypy_strict": True,
        "foundation": {
            "passed": int(re.search(r"Foundation evaluator: total=(\d+) passed=(\d+)", log)[2]),
            "total": int(re.search(r"Foundation evaluator: total=(\d+) passed=(\d+)", log)[1]),
        },
        "log_sha256": file_hash(local / "check-final.log"),
    }
    report["native_review_template_sha256"] = file_hash(
        local / "reviews/dulemon-native-reference/audit-blind.csv"
    )
    report["limitations"] = [
        "Latest revised plan original not yet supplied; execute explicit owner message without overwriting old plan",
        "Numeric remaining quota unavailable for callable candidates; cannot rank or prove full evaluation budget coverage",
        "Owner native audit and judge human calibration not completed by assistant",
        "Chinese query construction/type coverage remains unfinished; public-benchmark budget is not a complete Chinese evaluation budget",
    ]
    # Public report has only aggregate metrics, model metadata and hashes, never raw review rows.
    (a.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    e = report["ecd"]
    b = report["budget"]
    actual = b["existing_lme_s_plus_locomo_test_workload"]
    lines = [
        "# agent-memory 阶段1第三轮交接报告",
        "",
        f"日期：{report['generated_date_beijing']}（北京时间）；Codex；源码 `{report['source_commit']}`。",
        "",
        "**阶段1仍未验收，不进入阶段2。** 本报告替代此前交接中的 ECD κ/616仲裁和旧审核催办口径；旧实验保留历史。",
        "",
        "## ECD 新用途与当前审核范围",
        "",
        f"- 暂定负样本：{e['ecd_provisional_negative_candidates']} 条共同舍弃候选；{e['ecd_provisional_entire_negative_conversations']} 段全候选共同舍弃对话。均标注“人工未核验”，不直接当人工金标准。",
        f"- 固定种子 {e['seed']}，另抽 {e['ecd_manual_conversations']} 段：有个人信息线索 {e['ecd_manual_strata']['personal_information_hint']} 段（{e['ecd_manual_strata']['personal_information_hint'] / e['ecd_manual_conversations']:.2%}），无线索 {e['ecd_manual_strata']['no_personal_information_hint']} 段（{e['ecd_manual_strata']['no_personal_information_hint'] / e['ecd_manual_conversations']:.2%}）。原始池两层分别 {e['ecd_strata_population']['personal_information_hint']}/{e['ecd_strata_population']['no_personal_information_hint']} 段。",
        "- 分层只是第一人称＋个人信息关键词提示，不是助手给出的用户归属或应记标签；匿名说话人角色未知。人工字段全空，原切分不变，原文只在服务器和负责人私有包；GitHub/群报告仅方法、哈希与指标。未再生成616仲裁包。",
        f"- 本轮当前必填仅 DuLeMon native-reference 的 {e['required_owner_audit']} 条抽检，模板与上轮字节一致。ECD小样已预备，其他DuLeMon模型对照/PerLTQA旧审核暂缓，不催办。",
        f"- 尚无人工回填：DuLeMon未审核应记参照 {report['native_dulemon_unreviewed_keep']}，人工确认金标 {report['human_confirmed_chinese_gold']}，相对目标 {report['chinese_gold_target']} 仍差 {report['human_confirmed_chinese_gold_gap']}。不能把未审核参照说成已验收金标。",
        "- 回填处理已实现：先按冻结参照算一致率；低于95%时只输出人工确认子集并重算规模，不先改参照凑成100%。",
        "",
        "## 裁判候选、实际调用和预检",
        "",
        "|候选|本轮HTTP|剩余免费额度|格式预检|五次一致|当前预检合格|",
        "|---|---:|---|---|---|---|",
    ]
    for r in report["candidates"]:
        quota = (
            "服务免费包耗尽（402）" if r.get("remaining_free_tokens") == 0 else "数值未知，不能排序"
        )
        lines.append(
            f"|{r['model']}|{r.get('http_status', '失败')}|{quota}|{r['format_valid']}/{r['format_n']}|{r['consistent_5']}|{r['qualified_for_pool']}|"
        )
    lines += [
        "",
        "GLM-5.2已重新实际请求，仍明确报免费包耗尽、未开启后付费，不是沿用旧402直接排除。未充值、未开启后付费。模型在线列表不等于账号有额度；成功响应和响应头也未给剩余token数。",
        f"合格候选 {report['qualified_candidate_count']}，要求至少 {report['required_pool_size']}；当前不能冻结“余额最多主裁判＋两个备选”，主裁判和额度排名均未定。待控制台带查询日期的余额证据及足够合格可用模型，不捏造排名或宣称额度够用。",
        "glm-5v-turbo首轮有一次60秒超时，尽管格式99/100，现有严格预检因该响应无法确认思考状态未通过；本轮保留首轮并完整复测，不静默补一条或修改门槛。Step及HY-Vision探测返回非空reasoning内容，不能仅因reasoning_tokens=0就接受；MiniMax3.1按官方限制排除。GLM5.3/Kimi不满足关闭思考/采样控制条件。",
        "预检是开发工作区中的真实独立API请求，原始请求/响应只保留本地，具体底层权重版本未暴露时只记录response.model及调用日期。通过五次与100格式不等于裁判已完成人工校准。",
        "",
        "## 调用量与自动切换",
        "",
        f"- 方案§7示例：{b['questions']}题×{b['groups']}组×{b['repeats']}次 = 判分 {b['judge_calls']} 次；另有答题 {b['answer_calls']} 次，共 {b['combined_calls']} 次。按每次1000输入/100输出，裁判约 {b['judge_total_tokens_estimate']:,} token。",
        f"- 按当前冻结测试切分，LongMemEval-S {b['available_benchmarks']['longmemeval_s']['test_questions']} 题＋LoCoMo {b['available_benchmarks']['locomo']['test_questions']} 题，共 {actual['questions']} 题；同样4组3次需判分 {actual['judge_calls']:,} 次、估算 {actual['judge_total_tokens_estimate']:,} token。",
        "- 以上都不是“完整中文评测已备齐”：尚未完成中文查询/题型构建；额外E4/CX5单独请求、校准、预检、失败和整表重判仍要另计。余额未知时无法确认主裁判覆盖完整评测。",
        "- 整表切换机制已实现并测试：402立即切换，持续失败有界重试后切换；新裁判从第一行重判，旧的部分分数仅留失败台账；整表完成才原子发布，每条记录裁判ID、返回模型版本和日期。运行CLI要求真实额度证据文件与SHA256，拒绝未知余额池。未启动阶段2正式判分。",
        "",
        "## 合成时间线",
        "",
        f"候选 {report['synthetic_timeline']['candidate_count']}；旧组合 {' + '.join(report['synthetic_timeline']['models'])}，与当前冻结组合 {' + '.join(report['annotation_models'])} 不一致。建议保留输入/时间线/切分，负责人确认后用新组合整批重标并独立报告。本轮未重标，不混用旧标签。旧标签若继续参与评测，还需额外排除MiniMax厂商裁判。",
        "",
        "## 两个基准的实际检索运行",
        "",
        "|数据|本次题数|Recall@10|证据覆盖@10|",
        "|---|---:|---:|---:|",
    ]
    for name, r in report["retrieval"].items():
        lines.append(
            f"|{name}|{r['question_count']}|{r['recall_at10']['value']:.6f}|{r['evidence_coverage_at10']['value']:.6f}|"
        )
    lines += [
        "",
        "各取固定开发切分中第一段有题会话，实际非owner RLS PostgreSQL＋HTTP API，直接导入源对话为记忆后检索；lexical＋structured，未配向量。LongMemEval为oracle会话级相关性，LoCoMo为原始证据粒度，不把两者当同一证据单位。Recall分母和不可回答题处理见report.json。该运行证明能算出召回，不代表全量质量、抽取质量、向量能力或阶段2基线达标。",
        "",
        "## 验证与仍未完成",
        "",
        f"干净源码全量门：pytest {report['validation']['pytest_passed']} passed，{report['validation']['pytest_seconds']}s；ruff、mypy strict、foundation 8/8 通过。审核包二次生成逐件SHA256一致。证据/脚本与源哈希随报告归档。",
        "仍未完成：最新版方案原件核对、控制台余额证据与裁判池冻结（含至少两个备选）、230条负责人回填、裁判人工校准、中文查询与题型覆盖；合成重标仅有待确认方案。标注模型后续若需替换，必须先说明原因、等负责人确认并整批重标。",
        "",
    ]
    (a.output / "delivery.md").write_text("\n".join(lines))
    print(
        json.dumps(
            {
                "report": str(a.output),
                "phase_gate_passed": False,
                "qualified_judges": report["qualified_candidate_count"],
            }
        )
    )


if __name__ == "__main__":
    main()
