"""Verify private preparation reproducibility without emitting source text."""
import csv
import hashlib
import json
from pathlib import Path

from agent_memory.evals.human_review import digest

ROOT = Path('.local/phase1/round3/ecd180-review-v1')
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    original = ROOT / 'sample'
    repeated = ROOT / 'sample-reproduction'
    names = ['ecd180-preparation.csv', 'ecd180-preparation.jsonl', 'split-extended-private.json']
    hashes = {}
    for name in names:
        assert sha(original / name) == sha(repeated / name)
        hashes[name] = sha(original / name)
    manifest = json.loads((original / 'manifest.json').read_text())
    rows = [json.loads(line) for line in (original / names[1]).read_text().splitlines()]
    with (original / names[0]).open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        assert reader.fieldnames == manifest['columns']
        exported = list(reader)
    assert len(exported) == len(rows) == 180
    for row, csvrow in zip(rows, exported, strict=True):
        record_hash = row.pop('record_sha256')
        assert digest(row) == record_hash == csvrow['record_sha256']
        assert all(csvrow[k] == '' for k in ('human_memories', 'human_no_memories', 'human_reason'))
    frozen = json.loads(Path('.local/phase1/chinese-expansion-v2/ecd/split.json').read_text())
    extended = json.loads((original / names[2]).read_text())
    for side, ids in frozen.items():
        assert extended[side][:len(ids)] == ids
    for name, expected in manifest['protected_files_sha256'].items():
        assert sha(Path(name)) == expected
    historical = json.loads(Path('docs/reports/phase1-ecd180-preparation-2026-10-23/report.json').read_text())
    for name, expected in historical['protected_current_registry_sha256'].items():
        assert sha(Path(name)) == expected
    result = {'reproduced_sha256': hashes, 'row_hashes_verified': len(rows),
              'original_split_prefixes_unchanged': True, 'protected_files_unchanged': True,
              'current_adoption_registries_unchanged': True, 'human_columns_blank': True}
    target = ROOT / 'verification.json'
    target.write_text(json.dumps(result, indent=2) + '\n')
    target.chmod(0o600)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
