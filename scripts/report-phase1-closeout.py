"""Script-generated aggregate closeout; no source text, human answers or credentials."""

import argparse
import json
import re
import shutil
import subprocess
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from agent_memory.evals.datasets import file_hash
from agent_memory.evals.labeling import load_labels
from agent_memory.evals.metrics import agreement
from agent_memory.evals.runner import score


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, default=Path(".local/phase1/round3/closeout"))
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    root = a.root
    retrieval = root / "retrieval-policy-recorded"
    old = Path(".local/phase1/round3/retrieval-final/locomo")
    audits = json.loads((retrieval / "mapping-audit.json").read_text())

    def metrics(folder, name="predictions.jsonl"):
        r = score(folder / "dataset-local.jsonl", folder / name)
        return {
            k: r[k]
            for k in (
                "question_count",
                "scored_count",
                "metrics",
                "by_type",
                "rank_unit",
                "ci_unit",
            )
        }

    loco = {
        "before": metrics(old),
        "after": metrics(retrieval / "locomo"),
        "keyword_bm25": metrics(retrieval / "locomo", "keyword-predictions.jsonl"),
        "identical_questions_and_sources": file_hash(old / "dataset-local.jsonl")
        == file_hash(retrieval / "locomo/dataset-local.jsonl"),
        "source_sha256": file_hash(old / "dataset-local.jsonl"),
        "mapping_audit": {
            k: v
            for k, v in next(r for r in audits if r["dataset"] == "locomo").items()
            if k != "conversation_id"
        },
        "sql_diagnosis": {
            k: v
            for k, v in json.loads((root / "locomo-fts.json").read_text()).items()
            if k != "records"
        },
        "root_cause": "English simple plainto_tsquery used AND of every question word: zero lexical candidates; workspace structured fallback returned recent turns. Mapping and complete import independently verified; no metric/split change.",
    }
    la = [r for r in audits if r["dataset"] == "longmemeval_s"]
    long = {
        "result": metrics(retrieval / "longmemeval_s"),
        "sample_conversations": len(la),
        "selection": "first 50 question conversations in source order within unchanged fixed dev split; S version with distractors, not oracle",
        "source_documents": sum(r["source_documents"] for r in la),
        "successful_chunks": sum(r["mapped_chunks"] for r in la),
        "policy_rejected_chunks": sum(r["policy_rejected_chunks"] for r in la),
        "all_expected_chunks_accounted_for": all(r["expected_accounted_for"] for r in la),
        "successful_contents_exact": all(r["database_content_matches_source"] for r in la),
        "unmapped_hits": sum(r["unmapped_hits"] for r in la),
        "abstentions": sum(r["abstentions"] for r in la),
        "gold_queries_not_dropped": sum(r["questions"] for r in la) == 50,
        "full_text_import_complete": sum(r["policy_rejected_chunks"] for r in la) == 0,
    }
    glm = json.loads((root / "preflight-glm5v/glm-5v-turbo-summary.json").read_text())
    glm["decision"] = "通过" if glm["preflight_pass"] else "不通过"
    roles = json.loads(Path("docs/evals/phase1-round3-policy-v1.json").read_text())
    timeline = {
        "synthetic": True,
        "target_count": sum(
            1 for l in Path(".local/phase1/timeline-v1/items.jsonl").read_text().splitlines() if l.strip()
        ),
        "input_sha256": file_hash(Path(".local/phase1/timeline-v1/items.jsonl")),
        "split_sha256": file_hash(Path(".local/phase1/timeline-v1/split.json")),
        "prompt_sha256": file_hash(Path("docs/evals/prompts/annotation-v5.txt")),
        "original_failed_attempts": [],
        "models": [],
        "old_labels_reused": False,
        "human_review_complete": False,
        "counts_toward_real_chinese": False,
    }
    for model, directory, target in [
        ("deepseek-v4-pro", "timeline-deepseek", "original_failed_attempts"),
        ("mimo-v2.6-flash", "timeline-mimo", "original_failed_attempts"),
        ("deepseek-v4-pro-ga-260813", "timeline-v2-deepseek", "models"),
        ("hy4-preview", "timeline-v2-hy4", "models"),
    ]:
        folder = root / directory
        manifest = json.loads((folder / "manifest.json").read_text())
        files = sorted(folder.glob("shard-*/labels.jsonl"))
        labels = {key: value for f in files for key, value in load_labels(f).items()}
        ledgers = [r for f in folder.glob("shard-*/ledger.json") for r in json.loads(f.read_text())]
        timeline[target].append(
            {
                "model": model,
                "provider": "Ark" if model.startswith("deepseek-v4-pro-ga") else "TokenHub",
                "complete": (folder / "COMPLETE").exists(),
                "count": len(labels),
                "remaining": timeline["target_count"] - len(labels),
                "label_counts": dict(Counter(v.label for v in labels.values())),
                "http_status_counts": dict(
                    Counter(
                        str(at["http_status"])
                        for r in ledgers
                        for at in r["attempts"]
                        if "http_status" in at
                    )
                ),
                "total_tokens": sum(
                    r.get("usage", {}).get("total_tokens", 0)
                    for r in ledgers
                    if r["status"] == "validated" and not r["replayed"]
                ),
                "response_models": sorted(
                    {r["response_model"] for r in ledgers if "response_model" in r}
                ),
                "input_matches": manifest["items_sha256"] == timeline["input_sha256"],
                "prompt_matches": manifest["prompt_sha256"] == timeline["prompt_sha256"],
                "labels_sha256": file_hash(folder / "labels.jsonl")
                if (folder / "labels.jsonl").exists()
                else None,
                "evidence_hashes": {
                    str(f.relative_to(root)): file_hash(f)
                    for f in [*files, *folder.glob("shard-*/ledger.json"), folder / "manifest.json"]
                },
            }
        )
    timeline["complete"] = all(
        m["complete"] and m["count"] == timeline["target_count"] for m in timeline["models"]
    )
    timeline["agreement"] = None
    if timeline["complete"]:
        left = load_labels(root / "timeline-v2-deepseek/labels.jsonl")
        right = load_labels(root / "timeline-v2-hy4/labels.jsonl")
        if set(left) != set(right):
            raise ValueError("new label ID mismatch")
        timeline["agreement"] = agreement(
            [left[k].label for k in sorted(left)], [right[k].label for k in sorted(left)]
        )
        timeline["joint_keep"] = sum(left[k].label == right[k].label == "keep" for k in left)
        timeline["conflicts"] = sum(
            left[k].label != right[k].label or "uncertain" in (left[k].label, right[k].label)
            for k in left
        )
        timeline["audit_reference_count"] = (len(left) + 9) // 10
    timeline["qualifications"] = {
        "deepseek-v4-pro-ga-260813": json.loads(
            (
                root / "preflight-deepseek-v4-pro-ga-260813/deepseek-v4-pro-ga-260813-summary.json"
            ).read_text()
        ),
        "hy4-preview": json.loads(
            Path(".local/phase1/round3/preflight-hy4-preview/hy4-preview-summary.json").read_text()
        ),
    }
    validation = (root / "check-final.log").read_text()
    passed = re.search(r"(\d+) passed in ([\d.]+)s", validation)
    assert passed
    v = {
        "tests": int(passed[1]),
        "seconds": float(passed[2]),
        "ruff": "All checks passed!" in validation,
        "mypy": "Success: no issues found" in validation,
        "foundation": "total=8 passed=8 failed=0" in validation,
        "log_sha256": file_hash(root / "check-final.log"),
    }
    provenance = json.loads((retrieval / "source.json").read_text())
    relevant = [
        "infrastructure/retrieval.py",
        "application/retrieval.py",
        "evals/api_import.py",
        "evals/datasets.py",
        "evals/metrics.py",
        "evals/retrieval_diagnostics.py",
    ]
    source_match = {
        name: file_hash(Path("src/agent_memory") / name)
        == provenance["source_files"]["src/agent_memory/" + name]
        for name in relevant
    }
    report = {
        "date_beijing": datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat(),
        "generated_at": datetime.now(UTC).isoformat(),
        "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "working_tree_modified": bool(subprocess.check_output(["git", "status", "--porcelain"])),
        "phase_gate_passed": False,
        "phase2_started": False,
        "locomo": loco,
        "longmemeval_s": long,
        "glm5v": glm,
        "cross_cloud_demo": json.loads((root / "cross-cloud-demo/demo-summary.json").read_text()),
        "synthetic_timeline": timeline,
        "validation": v,
        "retrieval_run_source": {
            "commit": provenance["commit"],
            "dirty": provenance["dirty"],
            "relevant_files_match_current": source_match,
        },
        "current_judge_excluded_vendors": roles["judge_excluded_vendors"],
        "quota_verified": False,
        "judge_pool_frozen": False,
        "annotation_pair_public": roles["annotation_models"],
        "annotation_pair_synthetic": roles["synthetic_annotation_models"],
        "uncompleted": [
            "control-console quota evidence/order/freeze",
            "owner DuLeMon230 audit",
            "judge human calibration",
            "Chinese query/type coverage",
            "phase1 owner acceptance",
        ],
        "limits": [
            "one dev LoCoMo conversation; bootstrap CI degenerates, not population quality",
            "LongMemEval-S fixed50 dev questions, lexical+structured without vector/extraction; 47 chunks policy rejected; no question exclusion",
            "English full-text expression changed to english stemming/OR; no matching English GIN index or latency/capacity validation claimed",
            "Cross-cloud acceptance is mock HTTP only; no live quota failure/real formal score table",
            "Synthetic HY4 makes Tencent ineligible as judge; old three-candidate pool is not valid for new combined campaign",
        ],
    }
    if not timeline["complete"]:
        report["uncompleted"].append("synthetic whole-batch relabel incomplete")
    a.output.mkdir(parents=True, exist_ok=False)
    (a.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    (a.output / "synthetic-timeline.json").write_text(
        json.dumps(timeline, ensure_ascii=False, indent=2) + "\n"
    )
    lines = [
        "# agent-memory 阶段1第三轮收尾交接",
        "",
        f"日期：{report['date_beijing']}（北京时间）；Codex；源码 {report['source_commit'][:7]}；工作区状态见JSON。",
        "",
        "**阶段1仍未验收，不进入阶段2。** 本报告更新第三轮及Ark补充的当前状态；旧报告仅作历史。",
        "",
        "## LoCoMo 根因与修复",
        "",
        "根因是检索本身：英文 simple/plainto_tsquery 把整句所有词按AND连接，而不是证据映射或导入缺陷。改为English词干化/停用词过滤，再OR召回并按覆盖排名；中文路径与指标定义未改。",
        f"实际SQL对照：原AND查询 {loco['sql_diagnosis']['old_and_queries_without_matches']}/{loco['sql_diagnosis']['questions']} 题没有词法候选，结构化通道补入最近轮次；修复后有词法匹配的题数 {loco['sql_diagnosis']['new_or_queries_with_matches']}。",
        f"同一源文件SHA、同一 {loco['after']['question_count']} 题；原始 {loco['mapping_audit']['source_documents']} 轮次与映射一一对应，数据库内容哈希逐块匹配={loco['mapping_audit']['database_content_matches_source']}，证据缺失ID {loco['mapping_audit']['missing_evidence_ids']}，无法映射命中 {loco['mapping_audit']['unmapped_hits']}。检索返回条数分布 {loco['mapping_audit']['returned_counts']}。",
        "",
        "|运行|RT1@10 命中题/有证据题|Recall@10|证据覆盖@10|",
        "|---|---:|---:|---:|",
    ]
    for label, key in [
        ("修复前", "before"),
        ("修复后实际API", "after"),
        ("原始轮次朴素BM25", "keyword_bm25"),
    ]:
        r = loco[key]["metrics"]["RT1@10"]
        c = loco[key]["metrics"]["evidence_coverage@10"]
        lines.append(
            f"|{label}|{r['numerator']:g}/{r['denominator']:g}|{r['value']:.6f}|{c['value']:.6f}|"
        )
    lr = long["result"]["metrics"]["RT1@10"]
    lc = long["result"]["metrics"]["evidence_coverage@10"]
    lines += [
        "",
        f"LoCoMo另有 {loco['mapping_audit']['abstentions']} 道不可回答题，按冻结规则另算RT6，不把它们加进RT1分母。朴素BM25只使用问题与原始轮次，固定通用停用词与BM25参数，不读取答案。这里只是一段开发会话，不能把退化的cluster CI当总体置信度。",
        "",
        "## LongMemEval-S 固定开发50题",
        "",
        f"实际完成 {long['result']['question_count']} 题 / {long['sample_conversations']} 个问题会话，按固定dev切分内源顺序取样，不修改原切分。包含干扰会话，不是oracle。会话级RT1@10={lr['numerator']:g}/{lr['denominator']:g}={lr['value']:.6f}，CI95={lr['ci95']}；平均证据会话覆盖@10={lc['value']:.6f}。不可回答 {long['abstentions']} 题另算RT6。",
        f"原始轮次 {long['source_documents']}；分块后API成功 {long['successful_chunks']} 块、内容策略拒绝 {long['policy_rejected_chunks']} 块，全部预期块均已归账={long['all_expected_chunks_accounted_for']}，成功块逐字内容核验={long['successful_contents_exact']}。未绕过策略、未截断或改写原文，也未丢题；因此不能声称原文全部导入。无向量、无抽取，只报告这批开发样本的词法+结构化检索。",
        "",
        "## GLM-5V-Turbo 完整复测",
        "",
        "|模型|本轮结论|请求数|格式|五次一致|观测思考关闭|",
        "|---|---|---:|---:|---|---|",
        f"|glm-5v-turbo|{glm['decision']}|{glm['calls']}|{glm['format_valid']}/{glm['format_n']}|{glm['consistent_5']}|{glm['observed_disabled_thinking']}|",
        f"本轮明确结论：**{glm['decision']}**。此前失败和此前复测是不同历史批次；本报告以本轮完整批次为准。预检通过不等于额度足够或完成人工校准。",
        "",
        "## 跨渠道整表重判",
        "",
        f"运行入口 scripts/run-judge-table.py 已按provider选择独立凭据及URL，每条判分记录provider、model、response.model。--demo-cross-provider运行模拟腾讯第三条402后，丢弃前 {report['cross_cloud_demo']['discarded_partial_rows']} 条部分分数，由Ark从第一条重新完成 {report['cross_cloud_demo']['final_rows']} 条；最终只含Ark={report['cross_cloud_demo']['single_provider_model_version']}。真实模型调用 {report['cross_cloud_demo']['live_model_calls']}；这是HTTP MockTransport验收，未伪装成真实额度耗尽，也未冻结无余额证据的正式池。",
        "",
        "## 合成时间线重标（独立报告 synthetic-timeline.md / JSON）",
        "",
        f"负责人追加授权换模型后，新组合 {' + '.join(roles['synthetic_annotation_models'])} 对全部 {timeline['target_count']} 条重标；完成={timeline['complete']}。公开中文原组合 {' + '.join(roles['annotation_models'])} 不变，旧标签不混用，合成不计真实中文规模。",
        "腾讯现为新合成标注厂商，正式裁判入口采用所有当前标注厂商的保守并集排除；此前HY4裁判不再适用于含该批次的正式表，不能沿用“三候选已齐”的旧结论。余额排序和冻结继续等负责人截图。",
        "",
        "## 验证与未完成",
        "",
        f"全量 {v['tests']} tests passed / {v['seconds']}s；ruff={v['ruff']}、mypy strict={v['mypy']}、foundation={v['foundation']}。检索运行相关源文件与当前版本哈希一致={all(source_match.values())}；原运行起始commit和dirty状态及逐文件哈希核对见JSON。",
        "",
        "仍未完成：控制台额度证据、排序和裁判冻结；DuLeMon原生230条负责人回填；裁判人工校准；中文查询/题型覆盖；阶段1负责人验收。未代签人工结果，其他旧审核不催办。",
    ]
    if not timeline["complete"]:
        lines.append("本轮新合成整批重标仍未完成，见独立报告的阻塞和实际规模。")
    (a.output / "delivery.md").write_text("\n".join(lines) + "\n")
    tl = [
        "# 合成时间线整批重标独立报告",
        "",
        f"日期：{report['date_beijing']}；Codex；源码 {report['source_commit'][:7]}。",
        "",
        f"目标 {timeline['target_count']} 条；新批次完成={timeline['complete']}。输入、切分和提示SHA见JSON。原模型402部分批次只留历史，负责人已授权替换并整批重标。",
        "",
        "|批次|模型|渠道|有效标签|剩余|完成|",
        "|---|---|---|---:|---:|---|",
    ]
    for history, records in [
        ("已停止历史", timeline["original_failed_attempts"]),
        ("替代新整批", timeline["models"]),
    ]:
        for r in records:
            tl.append(
                f"|{history}|{r['model']}|{r['provider']}|{r['count']}|{r['remaining']}|{r['complete']}|"
            )
    if timeline["agreement"]:
        tl += [
            "",
            f"新组合全量κ与一致性：{json.dumps(timeline['agreement'], ensure_ascii=False)}。共同保留 {timeline['joint_keep']} 条，含分歧/uncertain {timeline['conflicts']} 条；10%抽检参照规模 {timeline['audit_reference_count']}。人工字段未填写，审核未通过，本轮仍只要求负责人填DuLeMon230。",
        ]
    tl += [
        "",
        "新旧标签不混用；新批次请求的实际model/version、usage及HTTP状态统计见JSON。仅合成数据，不计真实中文规模。标注厂商变动已同步正式裁判厂商排除；裁判额度排序等待截图，不充值或开启后付费。",
    ]
    (a.output / "synthetic-timeline.md").write_text("\n".join(tl) + "\n")
    shutil.copyfile(root / "check-final.log", a.output / "validation.log")
    print(
        json.dumps(
            {
                "output": str(a.output),
                "timeline_complete": timeline["complete"],
                "phase_gate_passed": False,
            }
        )
    )


if __name__ == "__main__":
    main()
