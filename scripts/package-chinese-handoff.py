"""Package authorized review files; ECD source/review text is never exported."""

import argparse
import hashlib
import json
import zipfile
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument("--root", type=Path, required=True)
p.add_argument("--report", type=Path, required=True)
p.add_argument("--output", type=Path, required=True)
a = p.parse_args()
a.output.mkdir(parents=True, exist_ok=False)
report = json.loads((a.report / "report.json").read_text())
assert report["phase_gate_passed"] is False and not report["human_review_complete"]
text = (a.report / "delivery.md").read_text()
examples = Path(".local/phase1/chinese-expansion-v2/diagnostic-examples.md")
text += "\n## 原候选诊断代表例子（仅授权审核附件，不入Git）\n\n" + examples.read_text()
md = a.output / "agent-memory阶段1真实中文补量交接-v2.md"
md.write_text(text)
files = {"交接报告.md": md, "report.json": a.report / "report.json"}
for name in (
    "validation-results.json",
    "validation-pytest.log",
    "validation-ruff.log",
    "validation-mypy.log",
    "validation-foundation.log",
    "validation-source-files.json",
):
    if (a.report / name).exists():
        files[name] = a.report / name
for directory in ("dulemon-native-reference", "dulemon-model-comparison"):
    for path in (a.root / "human-review-v1" / directory).glob("*"):
        if path.is_file():
            files[directory + "/" + path.name] = path
old = Path(".local/phase1/chinese-expansion-v2/human-review-v1")
for path in (old / "perltqa-native-reference").glob("*"):
    if path.is_file():
        files["perltqa-native-reference/" + path.name] = path
for key, path in files.items():
    assert "ecd" not in key.lower(), "ECD raw/review export forbidden"
    if path.name.endswith("-blind.jsonl"):
        for line in path.read_text().splitlines():
            row = json.loads(line)
            assert row.get("human_label") is None and row.get("human_reason") is None
manifest = {
    "report_source_commit": report["source_commit"],
    "model_names": report["models"],
    "phase_gate_passed": False,
    "files_sha256": {k: hashlib.sha256(v.read_bytes()).hexdigest() for k, v in files.items()},
    "ecd_review_local_only": str(a.root / "human-review-v1/ecd-model-comparison"),
    "native_dulemon_audit_unchanged": hashlib.sha256(
        (old / "dulemon-native-reference/audit-blind.jsonl").read_bytes()
    ).hexdigest()
    == hashlib.sha256(
        (a.root / "human-review-v1/dulemon-native-reference/audit-blind.jsonl").read_bytes()
    ).hexdigest(),
}
readme = """# 阶段1真实中文审核包 v2

本包替换此前只有原生参照的旧交接报告，记录最新全量双标结果；阶段1未验收。
只填写 human_label 与 human_reason，不改候选、来源、ID、记录哈希。
DuLeMon-native-reference：按原生参照执行10%抽检。若manifest显示audit未变，旧版已填写结果仍可按冻结哈希校验，不要求重做同一抽检。
DuLeMon-model-comparison：模型分歧仅作对照，不能筛除或自动改写原生金标；与原生抽检相同的任务无需重复填。
PerLTQA-native-reference：保留旧版原生基准抽检，单列模型生成来源，不计真实中文规模。
ECD许可未明确，含原文的仲裁/盲审材料只留服务器；本包只给其本地路径和报告中的聚合指标。
所有人工答案均为空；助手未签署、审核或计算任何虚假的人工通过率。
负责人回填后再按冻结协议计算盲审一致率，阈值95%；模型κ阈值0.7不变。
"""
archive = a.output / "agent-memory阶段1真实中文审核包-v2.zip"
with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED) as z:
    z.writestr("README.md", readme)
    z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    for name, path in files.items():
        z.write(path, name)
with zipfile.ZipFile(archive) as z:
    assert z.testzip() is None
result = {
    "report": str(md),
    "zip": str(archive),
    "zip_bytes": archive.stat().st_size,
    "zip_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
    "native_dulemon_audit_unchanged": manifest["native_dulemon_audit_unchanged"],
}
(a.output / "export-manifest.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
print(json.dumps(result, ensure_ascii=False))
