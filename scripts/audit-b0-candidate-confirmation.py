"""Audit frozen B0 candidate lifecycle without models, database writes or a running-job change."""
import ast
import hashlib
import json
import subprocess
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

repo = Path(__file__).resolve().parents[1]
source = repo / '.local/phase2/b0/source-B0'
sys.path.insert(0, str(source / 'src'))
from agent_memory.domain.enums import MemoryStatus, MemoryType, ScopeKind
from agent_memory.domain.errors import InvalidStatusTransition
from agent_memory.domain.models import Memory, MemoryScope

commit = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
assert commit == '1e9d6f3b25b58c85792344000d7e1b5a71a79737'
now = datetime.now(timezone.utc)
memory, _ = Memory.create(tenant_id=uuid4(), memory_id=uuid4(), version_id=uuid4(),
    memory_type=MemoryType.SEMANTIC, scope=MemoryScope(ScopeKind.TENANT, None, None),
    owner_user_id=uuid4(), content='fictional lifecycle audit', now=now, status=MemoryStatus.CANDIDATE)
checks = []
for initial in (MemoryStatus.CANDIDATE, MemoryStatus.NEEDS_REVIEW, MemoryStatus.ARCHIVED):
    try:
        result = replace(memory, status=initial).disable(MemoryStatus.ACTIVE, now)
        allowed = result.status is MemoryStatus.ACTIVE
        error = None
    except InvalidStatusTransition as exc:
        allowed, error = False, str(exc)
    assert allowed == (initial is MemoryStatus.ARCHIVED)
    checks.append({'from': initial.value, 'to': 'active', 'allowed': allowed, 'error': error})
files = ['src/agent_memory/domain/models.py', 'src/agent_memory/api/routes.py',
    'src/agent_memory/application/explicit_memory.py',
    'src/agent_memory/infrastructure/event_repositories.py',
    'docs/review-followup-2026-10-08.md']
routes = []
for file in sorted((source / 'src/agent_memory/api').glob('*.py')):
    tree = ast.parse(file.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in ('post', 'get', 'patch', 'delete', 'put', 'add_api_route'):
            routes.append({'file': str(file.relative_to(source)), 'line': node.lineno,
                'expression': ast.unparse(node)})
report = {'baseline_commit': commit, 'created_at': now.isoformat(),
    'method': 'all API route declarations and all source ACTIVE assignments reviewed; execute actual frozen domain transition used by public restore service; no HTTP/model/DB writes',
    'defect_id': 'B0-CANDIDATE-ACTIVATION-MISSING',
    'conclusion': '候选记忆无自动生效路径；冻结B0也未实现将原候选确认转为active的公开接口或流程。',
    'public_restore': 'POST /v1/memories/{memory_id}/restore exists, but candidate and needs_review to active are rejected; archived to active allowed',
    'explicit_write': 'POST /v1/memories creates a NEW memory ID; re-entering candidate content is not confirmation of the original candidate and is not measured as such',
    'historical_document_caveat': 'review-followup says approval uses an independent extraction path, but implemented worker only creates candidate; historical text is not implementation evidence',
    'second_measurement': {'status': 'not_applicable_missing_public_path', 'value': None,
        'reason': 'No state rewrite, no SQL activation, no new-memory recreation disguised as confirmation'},
    'current_run_interrupted': False, 'calibration': 'only sample after whole group completes; no early table',
    'transition_checks': checks, 'api_route_declarations': routes,
    'source_sha256': {f: hashlib.sha256((source / f).read_bytes()).hexdigest() for f in files}}
output = repo / 'docs/reports/phase2-b0-rebuild-2026-10-26/candidate-confirmation-audit.json'
output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({'report': str(output.relative_to(repo)), 'checks': checks, 'conclusion': report['conclusion']}, ensure_ascii=False))
