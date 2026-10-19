"""Reproduce phase-0 gates and fingerprint a disposable migrated PostgreSQL database."""
import argparse
import asyncio
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from testcontainers.community.postgres import PostgresContainer

from agent_memory.api.app import create_app
from agent_memory.api.event_schemas import EventBatchRequest, EventRequest
from agent_memory.api.schemas import ScopeRequest, SearchRequest
from agent_memory.config import Settings
from agent_memory.domain.events import MAX_PAYLOAD_BYTES, MAX_PAYLOAD_DEPTH

ROOT = Path(__file__).resolve().parents[1]


def run(args):
    return subprocess.check_output(args, cwd=ROOT, text=True).strip()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def scan_counts(path):
    raw = json.loads(path.read_text())
    found = [(p['name'], v['id']) for p in raw['dependencies'] for v in p.get('vulns', [])]
    return {'packages_scanned': len(raw['dependencies']), 'findings':len(found),
            'unique_advisories':len({v for _,v in found}),
            'affected_packages':sorted({name for name,_ in found})}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--audit-input', type=Path, default=Path('.local/phase0'))
    args = p.parse_args()
    if args.output.exists():
        p.error('output exists; use a fresh path to preserve prior evidence')
    state = {'commit':run(['git','rev-parse','HEAD']),
             'dirty':run(['git','status','--porcelain'])}
    args.output.mkdir(parents=True)
    scratch = ROOT/'.local/phase0'
    scratch.mkdir(parents=True, exist_ok=True)
    junit = scratch/'validated.junit.xml'
    env = dict(os.environ)
    for key in ('ARK_API_KEY', 'MEMORY_EXTRACTION_TOKEN', 'MEMORY_EMBEDDING_TOKEN'):
        env.pop(key, None)
    checks = [
        ('pytest',[sys.executable,'-m','pytest','-q','--junitxml',str(junit)]),
        ('ruff',['uv','run','ruff','check','src','tests','migrations']),
        ('mypy',['uv','run','mypy','--strict','src']),
        ('foundation',[sys.executable,'-m','agent_memory.evals.foundation_runner'])]
    gates = {}
    for name, cmd in checks:
        result = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, check=False)
        (args.output/(name+'.log')).write_text(result.stdout+result.stderr)
        gates[name] = {'command':cmd,'exit_code':result.returncode}
        if result.returncode:
            raise SystemExit(f'{name} failed; inspect {args.output}/{name}.log')
    suite = ElementTree.parse(junit).getroot()
    totals = {key:sum(int(x.attrib.get(key,0)) for x in suite.iter('testsuite'))
              for key in ('tests','failures','errors','skipped')}
    if any(totals[k] for k in ('failures','errors','skipped')):
        raise SystemExit('A skipped or failed test cannot satisfy phase0')
    gates['pytest'].update(totals)
    gates['mypy']['source_files'] = int(re.search(r'in (\d+) source files',
        (args.output/'mypy.log').read_text()).group(1))
    summary = re.search(r'total=(\d+) passed=(\d+) failed=(\d+) tenant_leaks=(\d+) deleted_memory_hits=(\d+)',
                        (args.output/'foundation.log').read_text())
    gates['foundation'].update(dict(zip(('total','passed','failed','tenant_leaks','deleted_memory_hits'),
                                      map(int,summary.groups()))))
    if gates['foundation']['failed'] or gates['foundation']['tenant_leaks'] or gates['foundation']['deleted_memory_hits']:
        raise SystemExit('foundation correctness regression')
    database = {}
    with PostgresContainer('pgvector/pgvector:pg16', driver='psycopg') as postgres:
        config = Config('alembic.ini')
        config.set_main_option('sqlalchemy.url',postgres.get_connection_url())
        command.upgrade(config,'head')
        engine = create_engine(postgres.get_connection_url())
        try:
            with engine.connect() as connection:
                database['server_version'] = connection.scalar(text('SELECT version()'))
                database['pgvector_version'] = connection.scalar(text("SELECT extversion FROM pg_extension WHERE extname='vector'"))
                database['migration'] = connection.scalar(text('SELECT version_num FROM alembic_version'))
                database['embedding_indexes'] = list(connection.scalars(text("SELECT indexdef FROM pg_indexes WHERE tablename='memory_embeddings'")))
                database['app_role'] = dict(connection.execute(text("SELECT rolname,rolsuper,rolbypassrls FROM pg_roles WHERE rolname='agent_memory_app'")).mappings().one())
                database['rls'] = [dict(row) for row in connection.execute(text("SELECT c.relname,c.relrowsecurity,c.relforcerowsecurity FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relkind='r' AND c.relname<>'alembic_version' ORDER BY c.relname")).mappings()]
        finally:
            engine.dispose()
    database['scope'] = 'disposable Testcontainers migrated DB only; not the persistent deployment'
    database['image_id'] = run(['docker','image','inspect','pgvector/pgvector:pg16','--format','{{.Id}}'])
    app = create_app(Settings())
    try:
        offset = next(x for x in app.openapi()['paths']['/v1/memories/{memory_id}/versions']['get']['parameters'] if x['name']=='offset')['schema']
    finally:
        asyncio.run(app.state.engine.dispose())
    before, after = (args.audit_input/'audit-before.json', args.audit_input/'audit-after.json')
    for file in (before,after,args.audit_input/'requirements-before.txt',args.audit_input/'requirements-after.txt'):
        shutil.copyfile(file,args.output/file.name)
    source = ROOT/'docs/agent-memory面试级完善方案.md'
    files = [*ROOT.joinpath('src').rglob('*.py'),*ROOT.joinpath('tests').rglob('*.py'),
             *ROOT.joinpath('migrations').rglob('*.py'),ROOT/'pyproject.toml',ROOT/'uv.lock',
             Path(__file__),ROOT/'scripts/check.sh']
    report = {'generated_at_utc':datetime.now(UTC).isoformat(),
        'date_beijing':datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat(),
        'source':state,'source_sha256':{str(f.relative_to(ROOT)):sha(f) for f in files},
        'source_document':{'path':str(source.relative_to(ROOT)),'bytes':source.stat().st_size,'sha256':sha(source),
                           'message_id':'om_x100b62797c9004a4dd38ee4fc3fdb0e'},
        'environment':{'os':platform.platform(),'python':platform.python_version(),'cpus':os.cpu_count(),
            'affinity':sorted(os.sched_getaffinity(0)),'meminfo':{line.split(':',1)[0]:line.split(':',1)[1].strip() for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith(('MemTotal:','MemAvailable:'))},
            'cpu':next((line.split(':',1)[1].strip() for line in Path('/proc/cpuinfo').read_text().splitlines() if line.startswith('model name')), 'unknown'),
            'docker':run(['docker','version','--format','{{.Server.Version}}']),
            'packages':{d.metadata['Name']:d.version for d in importlib.metadata.distributions()}},
        'database':database,'gates':gates,
        'resource_bounds':{'body_bytes':Settings().max_request_body_bytes,
            'search':SearchRequest.model_json_schema()['properties'],
            'scope':ScopeRequest.model_json_schema()['properties'],
            'events_per_batch':EventBatchRequest.model_json_schema()['properties']['events']['maxItems'],
            'event_types':EventRequest.model_json_schema()['properties']['event_type']['enum'],
            'payload_bytes':MAX_PAYLOAD_BYTES,'payload_container_depth':MAX_PAYLOAD_DEPTH,
            'version_offset_schema':offset},
        'audit':{'before':scan_counts(before),'after':scan_counts(after),
            'tool_version':run(['uv','tool','run','pip-audit','--version']),
            'mode':'PyPI advisory service; frozen all-groups requirements, Linux environment markers; resolved exact versions; no-deps/disable-pip, not arbitrary re-resolution',
            'lock_before_sha256':hashlib.sha256(subprocess.check_output(['git','show','1e2730c:uv.lock'],cwd=ROOT)).hexdigest(),
            'lock_after_sha256':sha(ROOT/'uv.lock')},
        'runtime_model_calls':0,'runtime_model_tokens':0,
        'ai':{'tool':'Codex','exact_model_version':'unverified','user_review':'pending'},
        'gate_status':'engineering checks passed; owner and independent review pending; stage1 not started'}
    (args.output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str)+'\n')
    content=f'''# agent-memory 阶段 0 交付报告

生成日期（北京时间）：{report['date_beijing']}；执行：Codex（具体模型版本未核实）。
代码：`{state['commit']}`；采样/验证前工作树：{'有修改' if state['dirty'] else '干净'}。

## 结论

阶段0的修复与核实已形成工程交付，等待负责人及独立复核。方案第13节要求验收后再进入下一阶段，因此本次未启动阶段1。B0标签只冻结修复后源码，不表示阶段2全指标基线已测完。

| 检查 | 结果 |
|---|---|
| 全量pytest | {totals['tests']}通过，失败{totals['failures']}，错误{totals['errors']}，跳过{totals['skipped']} |
| Ruff | 通过 |
| strict mypy | {gates['mypy']['source_files']}个源码文件通过 |
| Foundation | {gates['foundation']['passed']}/{gates['foundation']['total']}，租户泄漏{gates['foundation']['tenant_leaks']}，删除命中{gates['foundation']['deleted_memory_hits']} |
| 锁文件漏洞扫描 | {report['audit']['before']['findings']}条报告项→{report['audit']['after']['findings']}；去重公告{report['audit']['before']['unique_advisories']}→{report['audit']['after']['unique_advisories']} |
| 外部运行时模型 | 调用{report['runtime_model_calls']}次，token {report['runtime_model_tokens']} |

所有数字由本脚本生成，原始日志、扫描JSON及环境指纹同目录保存；漏洞扫描仅表示该时点该服务对锁定依赖的已知公告，不表示不存在其他漏洞。开发AI自身用量不可得，不计入运行时模型台账。

## 六项处置

1. InvalidScope：原入口无映射，现返回422/INVALID_SCOPE和关联request_id，不回显异常内容；新增缺workspace等API回归。
2. foundation_runner：逐case捕获普通Exception，只存异常类型/失败码且继续其余case；CancelledError/系统退出不吞掉，失败退出码非0。
3. 事件接口：确认原HTTP只收tool.result。新增conversation.message，payload为user/assistant角色及受限summary；不允许system角色，不改变scope授权。写入/幂等/隔离经过真实PG验证，规则提取器对非tool事件仍返回空，LLM仍只读取受限且不可信的summary；没有冒称所有对话都自动提取成功。迁移{database['migration']}仅在临时测试DB执行；有对话数据时拒绝有损降级。
4. 租约时钟：原claim/renew/succeed/fail接受应用时间，现用PG clock_timestamp()；领取按DB筛选，拿锁后再次读wall clock，避免事务开始时间过期。Outbox→job、重建和admin调度也用DB时间。内存适配器继续可注入时钟用于领域单测。快/慢机器时间、事务内过期、旧owner不能提交已验证。
5. 资源边界：整体请求体{report['resource_bounds']['body_bytes']}字节（Content-Length与实际流双重检查），缓冲后再解析/落库；查询、向量、事件条数/深度等上下界见report.json，版本offset现有限制。未引入索引/缓存/重排等优化，也不称完整抗DoS系统。
6. 锁文件：扫描前后全组冻结requirements与原始公告保留。升级PyJWT/urllib3及开发测试工具pytest/pytest-asyncio；测试工具跨主版本是为修复已知公告，完整回归已覆盖。详见audit-before.json、audit-after.json及uv.lock差异。

## 复现

```bash
uv sync --all-groups --frozen
uv export --frozen --all-groups --no-emit-project --no-hashes --format requirements-txt > .local/requirements.txt
uv tool run pip-audit -r .local/requirements.txt --disable-pip --no-deps --format json --output .local/audit.json
uv run python scripts/phase0-evidence.py --output .local/reproduce-phase0 --audit-input .local/phase0
```

最后命令复跑四道门与临时数据库指纹；audit-input须提供前后审计JSON与requirements原件，可复制本报告目录的四个文件后使用。Docker只在tx运行，不接触持久化业务DB。源码/脚本/锁文件散列在report.json；原始附件保持作者署名及字节内容。

## 尚待验收

负责人验收与独立复核抽查两条开发记录尚未完成，不能编造成已通过。下一阶段的模型预检、数据集下载、κ校准、指标框架及全指标B0未做；无生产部署、无ANN索引或性能提升声明。应用时钟仍可用于非租约业务审计/事件occurred_at，未宣称全系统时间源统一。
'''
    (args.output/'delivery.md').write_text(content)
    print(json.dumps({'source':state['commit'],'tests':totals,'audit':report['audit']['after'],
                      'report':str(args.output/'delivery.md')},ensure_ascii=False))


if __name__=='__main__':
    main()
