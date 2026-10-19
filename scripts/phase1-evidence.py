"""Generate phase1 delivery evidence; raw texts, credentials and model reasons never copied."""

import argparse
import hashlib
import json
import os
import platform
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo


def read(path):
    return json.loads(path.read_text()) if path.exists() else None


def run(args):
    root = args.input
    source_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], text=True))
    source_files = {}
    for folder in ["src", "tests", "scripts", "docs/evals"]:
        for path in sorted(Path(folder).rglob("*")):
            if (
                path.is_file()
                and "__pycache__" not in path.parts
                and path.suffix in [".py", ".txt", ".json", ".md"]
            ):
                source_files[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    args.output.mkdir(parents=True, exist_ok=False)
    gates = []
    commands = [
        ("pytest", ["uv", "run", "pytest", "-q"]),
        ("ruff", ["uv", "run", "ruff", "check", "src", "tests", "migrations"]),
        ("mypy", ["uv", "run", "mypy", "--strict", "src"]),
        ("foundation", ["uv", "run", "python", "-m", "agent_memory.evals.foundation_runner"]),
    ]
    for name, command in commands:
        start = time.monotonic()
        result = subprocess.run(
            command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False
        )
        (args.output / (name + ".log")).write_text(result.stdout)
        gates.append(
            {
                "gate": name,
                "command": command,
                "exit_code": result.returncode,
                "seconds": time.monotonic() - start,
            }
        )
        print(name, result.returncode, flush=True)
    manifests = {
        name: read(root / path)
        for name, path in {
            "public": "normalized-v3/manifest.json",
            "timeline": "timeline-v1/manifest.json",
            "public_chinese_candidates": "public-chinese-v1/manifest.json",
            "specialist_candidates": "specialist-candidates-v2/manifest.json",
        }.items()
    }
    preflights = {
        name: read(root / folder / (name + "-summary.json"))
        for name, folder in {
            "deepseek-v4.1-flash": "preflight-v1",
            "minimax-m3": "preflight-minimax-json-v2",
            "glm-5.2": "preflight-paced-v1",
            "hy3": "preflight-hy3-paced-v1",
        }.items()
    }
    annotations = {}
    for folder in ["labels-a-v1", "labels-b-v1", "public-labels-a-v1", "public-labels-b-format-v2"]:
        directory = root / folder
        ledger = read(directory / "ledger.json") or []
        labels = directory / "labels.jsonl"
        annotations[folder] = {
            "complete": (directory / "COMPLETE").exists(),
            "labels": sum(1 for _ in labels.open()) if labels.exists() else 0,
            "validated_batches": sum(x.get("status") == "validated" for x in ledger),
            "failed_batches": sum(x.get("status") == "failed" for x in ledger),
            "unknown_or_inflight_batches": sum(x.get("status") == "started" for x in ledger),
            "replay_batches": sum(bool(x.get("replayed")) for x in ledger),
            "logged_usage": {
                field: sum((x.get("usage") or {}).get(field, 0) for x in ledger)
                for field in ["prompt_tokens", "completion_tokens", "total_tokens"]
            },
            "labels_sha256": hashlib.sha256(labels.read_bytes()).hexdigest()
            if labels.exists()
            else None,
            "ledger_sha256": hashlib.sha256((directory / "ledger.json").read_bytes()).hexdigest()
            if ledger
            else None,
        }
    reviews = {
        folder: read(root / folder / "model-agreement.json")
        for folder in ["timeline-review-v1", "public-review-v1"]
    }
    smoke = {}
    for path in (root / "public-smoke-v2").glob("*/report/report.json"):
        data = read(path)
        smoke[path.parts[-3]] = {
            key: data[key]
            for key in [
                "question_count",
                "scored_count",
                "metrics",
                "by_type",
                "metadata",
                "rank_unit",
            ]
        }
    report = {
        "created_at": datetime.now(UTC).isoformat(),
        "phase": 1,
        "phase_gate_passed": False,
        "status": "first delivery; requires owner decisions and human labels; no phase2",
        "source": {
            "commit": source_commit,
            "uncommitted_at_start": dirty,
            "files_sha256": source_files,
            "B0": subprocess.check_output(["git", "rev-parse", "B0^{}"], text=True).strip(),
        },
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "logical_cpus": os.cpu_count(),
            "disposable_database": read(root / "public-smoke-v2/environment.json"),
        },
        "gates": gates,
        "dataset_manifests": manifests,
        "selected_preflights": preflights,
        "ark_probes": {
            "family_id": read(root / "ark-access-and-batch.json"),
            "versioned_id": read(root / "ark-access-and-batch-versioned.json"),
        },
        "annotations": annotations,
        "model_agreement": reviews,
        "public_smoke": smoke,
        "limits": [
            "Source changes were uncommitted during initial exploratory provider calls; prompt/body hashes retained.",
            "Preflight is synthetic exact-match format checking, not judge calibration.",
            "Historical developer debug probes included 14 extra MiniMax calls without a retained token ledger; do not claim complete cost accounting.",
            "Template and public-derived candidate counts are not approved gold counts.",
            "Human arbitration/audit not complete; audit acceptance threshold still awaits owner.",
            "Ark requested chat model returned 404; no unapproved substitute.",
            "TokenHub annotation returned HTTP402; further paid calls paused pending owner account check. Stopped in-flight usage may be unknown.",
            "Source overlap, graded memory relevance and all experimental observation adapters need completion before full B0.",
            "Specialist sets are candidate templates, not executed safety/fault experiments.",
        ],
    }
    (args.output / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    )
    (args.output / "dataset-manifests.json").write_text(
        json.dumps(manifests, ensure_ascii=False, indent=2) + "\n"
    )
    (args.output / "model-preflight.json").write_text(
        json.dumps(
            {"selected": preflights, "ark": report["ark_probes"]}, ensure_ascii=False, indent=2
        )
        + "\n"
    )
    text = [
        f"> 🤖 由 Codex 生成 · {datetime.now(ZoneInfo('Asia/Shanghai')).date()} · 来源 agent-memory@{source_commit[:7]} · 工具 lark-cli profile codex",
        "",
        "# agent-memory 阶段1首批交付报告（待人审，未验收）",
        "",
        f"源码：`{source_commit}`；执行开始未提交修改：{dirty}。",
        "B0标签保持阶段0版本；本轮不进入阶段2。",
        "",
        "## 已交付工程",
        "",
        "- 评测单入口、SDK/API导入、来源ID与多来源记忆映射、受限RLS血缘观察。",
        "- 手算公式回归、66指标目录、不可覆盖报告、数据/配置/源码哈希、配对对比。",
        "- 公开语料归一化、分会话切分、中文合成/公开候选、专项候选生成。",
        "- 真实模型预检、独立标注、重放缓存、调用账本、盲审导出。",
        "",
        "## 四道门",
        "",
        "|门|退出码|耗时秒|",
        "|---|---|---|",
    ]
    for gate in gates:
        text.append(f"|{gate['gate']}|{gate['exit_code']}|{gate['seconds']:.2f}|")
    text += [
        "",
        "完整测试数见pytest.log，类型文件数见mypy.log；不复制历史阶段0数字。",
        "",
        "## 模型预检",
        "",
        "|模型|格式合法/100|五次一致|预检达标|",
        "|---|---|---|---|",
    ]
    for name, data in preflights.items():
        text.append(
            f"|{name}|{data.get('format_valid') if data else '未完成'}|{data.get('consistent_5') if data else '未完成'}|{data.get('preflight_pass') if data else '未完成'}|"
        )
    text += [
        "",
        "保留初轮429与MiniMax96/100失败，后续加JSON约束达到99/100。预检通过不是裁判与人工一致性通过。",
        "Ark向量单条/两段输入都返回一个1024维向量，不能宣称独立文本批量已实现。对话模型两个ID均404，须负责人确认。",
        "",
        "## 公开数据与冒烟",
        "",
        "清单见dataset-manifests.json（原件字节数/SHA256、来源提交、许可、异常）。",
        "三份公开集各选开发集一段历史，431题，经临时PostgreSQL非属主角色和实际SDK/API跑通；没有向量模型、没有网络服务容量结论。逐项值在report.json/public_smoke。",
        "",
        "## 标注与人工闸门",
        "",
    ]
    for name, state in annotations.items():
        text.append(f"- {name}：标签{state['labels']}，完成标记{state['complete']}。")
    for name, state in reviews.items():
        text.append(
            f"- {name}："
            + (
                f"模型间κ={state.get('kappa')}，一致率={state.get('agreement')}，仲裁{state.get('conflict_count')}条、抽检{state.get('audit_count')}条。"
                if state
                else "未生成最终配对材料。"
            )
        )
    text += [
        "",
        "请负责人填写盲审材料的human_label与human_reason，不能由助手代签。公开与合成分别报告，候选数量不当作金标数量。",
        "",
        "## 需要负责人决定/完成",
        "",
        "1. 确认Ark可调用的原定模型/接入点ID；如果换型需明确选择，不自动替换。",
        "2. 确认TokenHub账户余额/配额/状态，HTTP402恢复后才能续跑；无需重发密钥。",
        "3. 确认人工10%抽检一致率阈值：原方案未给数值，建议≥90%；模型间κ仍保持≥0.7。",
        "4. 实际完成仲裁、10%盲审及去重全量人工确认。",
        "",
        "## 未完成与恢复入口",
        "",
        "TokenHub公开中文标注遇HTTP402，后续模型调用已暂停；已有缓存保留。阶段1尚未验收：人审金标、原始中文负样本代表性、专项集审核、来源跨组重叠核对、记忆分级相关度、部分复合观测适配和质量CI冻结仍需补齐。不能称“只差点确认”、不能把未执行实验记成0。",
        "命令与边界见docs/evals/README.md；任务记录见docs/devlog/tasks-phase1.md。复现时使用新的.local输出目录，原始数据与完整模型答复不进Git。",
        "",
        "## 已知代价与来源",
        "",
        "模型调用有外部随机性/限流，公开基准训练污染未确认；模板数据语言多样性有限；单人仲裁没有第二位人工复核。初期14次诊断调用未留token账本，资源总量不能声称完整。",
        "代码、测试、报告由Codex生成；具体开发模型版本未核实；负责人尚未独立复核。",
    ]
    (args.output / "delivery.md").write_text("\n".join(text) + "\n")
    print("report", args.output, flush=True)
    if any(g["exit_code"] for g in gates):
        raise SystemExit("gates failed; report remains incomplete")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--input", type=Path, default=Path(".local/phase1"))
    p.add_argument("--output", type=Path, required=True)
    run(p.parse_args())
