"""Fixed-dev LoCoMo diagnosis and LongMemEval-S session recall, actual PG/API."""

import argparse
import asyncio
import hashlib
import json
import subprocess
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx
import jwt
from alembic import command
from alembic.config import Config
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from testcontainers.community.postgres import PostgresContainer

from agent_memory.api.app import create_app
from agent_memory.config import Settings
from agent_memory.domain.enums import ScopeKind
from agent_memory.domain.models import MemoryScope
from agent_memory.evals.api_import import import_conversation, retrieve_sources
from agent_memory.evals.datasets import Conversation, file_hash
from agent_memory.evals.retrieval_diagnostics import audit_mapping, keyword_predictions
from agent_memory.evals.runner import save_report
from agent_memory.sdk import MemoryClient


async def execute(database_url, normalized, output, inspection):
    tenant, user = uuid4(), uuid4()
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = (
        key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    chosen = []
    for dataset, minimum in [("locomo", 1), ("longmemeval_s", 50)]:
        split = json.loads((normalized / f"{dataset}-split.json").read_text())
        dev = set(split["dev"])
        available = [
            Conversation.model_validate_json(line)
            for line in (normalized / f"{dataset}.jsonl").open()
            if json.loads(line)["conversation_id"] in dev
        ]
        selected = [conv for conv in available if conv.questions][:minimum]
        if sum(len(c.questions) for c in selected) < minimum:
            raise ValueError("development split has insufficient questions")
        chosen.extend((dataset, conv) for conv in selected)
    for dataset in {d for d, _ in chosen}:
        folder = output / dataset
        folder.mkdir()
        (folder / "dataset-local.jsonl").write_text(
            "".join(c.model_dump_json() + "\n" for d, c in chosen if d == dataset)
        )
        (folder / "config.json").write_text(
            json.dumps(
                {
                    "mode": "direct",
                    "k": 10,
                    "model_calls": 0,
                    "selection": "first source-order conversations in unchanged fixed dev split",
                    "normalized_sha256": file_hash(normalized / f"{dataset}.jsonl"),
                    "split_sha256": file_hash(normalized / f"{dataset}-split.json"),
                    "channel": "PostgreSQL english stem/stopword OR + structured; vector absent",
                    "ci_unit": "conversation cluster",
                    "full_corpus": False,
                }
            )
        )
    audits = []
    workspaces = ["eval-" + str(i) for i in range(len(chosen))]
    token = jwt.encode(
        {
            "iss": "eval-smoke",
            "aud": "eval-api",
            "sub": str(user),
            "tenant_id": str(tenant),
            "roles": ["developer"],
            "permissions": ["memory:read", "memory:write"],
            "allowed_workspace_ids": workspaces,
            "exp": datetime.now(UTC) + timedelta(hours=3),
        },
        key,
        algorithm="RS256",
    )
    app = create_app(
        Settings(
            database_url=database_url,
            jwt_public_key=public,
            jwt_issuer="eval-smoke",
            jwt_audience="eval-api",
        )
    )
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://eval"
        ) as http:
            sdk = MemoryClient(http, token=token)
            for workspace, (dataset, conv) in zip(workspaces, chosen, strict=True):
                folder = output / dataset
                rejected = []
                mapping = await import_conversation(
                    sdk,
                    conv,
                    MemoryScope(ScopeKind.WORKSPACE, workspace, None),
                    mode="direct",
                    rejected=rejected,
                )
                predictions = await retrieve_sources(sdk, conv, mapping, workspace_id=workspace)
                baseline = keyword_predictions(conv)
                audit = audit_mapping(conv, mapping)
                audit["policy_rejected_chunks"] = len(rejected)
                audit["expected_accounted_for"] = (
                    len(mapping) + len(rejected) == audit["expected_chunks"]
                )
                (folder / ("rejected-" + workspace + ".json")).write_text(
                    json.dumps(rejected, indent=2)
                )
                expected_hashes = {
                    (d.source_id, part): hashlib.sha256(
                        d.text[start : start + 4000].encode()
                    ).hexdigest()
                    for d in conv.documents
                    for part, start in enumerate(range(0, len(d.text), 4000))
                }
                versions = {r["version_id"] for r in mapping}
                with inspection.connect() as conn:
                    dbrows = conn.execute(
                        text(
                            "SELECT memory_version_id, content FROM memory_versions WHERE tenant_id=:tenant"
                        ),
                        {"tenant": str(tenant)},
                    ).all()
                content = {
                    str(vid): hashlib.sha256(txt.encode()).hexdigest()
                    for vid, txt in dbrows
                    if str(vid) in versions
                }
                audit["database_version_count"] = len(content)
                audit["database_content_matches_source"] = len(content) == len(mapping) and all(
                    content.get(r["version_id"])
                    == expected_hashes[(r["source_id"], r["part"])]
                    == r["content_sha256"]
                    for r in mapping
                )
                audit["unmapped_hits"] = sum(p["unmapped_hits"] for p in predictions)
                audit["returned_counts"] = dict(Counter(p["memory_results"] for p in predictions))
                audit["dataset"] = dataset
                audit["conversation_id"] = conv.conversation_id
                audits.append(audit)
                (folder / ("mapping-" + workspace + ".json")).write_text(json.dumps(mapping))
                for name, rows in [("predictions", predictions), ("keyword-predictions", baseline)]:
                    with (folder / (name + ".jsonl")).open("a") as stream:
                        stream.write("".join(json.dumps(p) + "\n" for p in rows))
                (output / "mapping-audit.json").write_text(json.dumps(audits, indent=2))
                print(
                    json.dumps(
                        {
                            "dataset": dataset,
                            "completed_conversations": sum(d["dataset"] == dataset for d in audits),
                            "imported": len(mapping),
                            "questions": len(predictions),
                            "database_exact": audit["database_content_matches_source"],
                        }
                    ),
                    flush=True,
                )
            for dataset in {d for d, _ in chosen}:
                folder = output / dataset
                for name, report in [
                    ("predictions", "report"),
                    ("keyword-predictions", "keyword-report"),
                ]:
                    save_report(
                        folder / report,
                        folder / "dataset-local.jsonl",
                        folder / (name + ".jsonl"),
                        folder / "config.json",
                        "direct",
                        {"RT1", "RT2", "RT3", "RT4", "RT5", "RT6"},
                    )
    finally:
        await app.state.engine.dispose()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--normalized", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if ".local" not in args.output.resolve().parts:
        parser.error("smoke raw sources must remain ignored .local/")
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "source.json").write_text(
        json.dumps(
            {
                "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
                "dirty": bool(subprocess.check_output(["git", "status", "--porcelain"])),
                "source_files": {
                    str(p): file_hash(p) for p in Path("src/agent_memory").rglob("*.py")
                },
            }
        )
    )
    with PostgresContainer(
        "pgvector/pgvector:pg16",
        username="agent_memory",
        password="disposable-smoke-only",
        dbname="agent_memory",
        driver="psycopg",
    ) as pg:
        url = pg.get_connection_url()
        config = Config("alembic.ini")
        config.set_main_option("sqlalchemy.url", url)
        command.upgrade(config, "head")
        engine = create_engine(url)
        with engine.begin() as conn:
            conn.execute(
                text(
                    "CREATE ROLE eval_app LOGIN PASSWORD 'disposable-app-only' NOSUPERUSER NOBYPASSRLS"
                )
            )
            conn.execute(text("GRANT agent_memory_app TO eval_app"))
        with engine.connect() as conn:
            fingerprint = {
                "postgres": conn.scalar(text("SELECT version()")),
                "pgvector": conn.scalar(
                    text("SELECT extversion FROM pg_extension WHERE extname='vector'")
                ),
                "docker_image_id": pg.get_wrapped_container().image.id,
                "migration_head": conn.scalar(text("SELECT version_num FROM alembic_version")),
            }
        (args.output / "environment.json").write_text(json.dumps(fingerprint, indent=2))
        engine.dispose()
        appurl = (
            make_url(url)
            .set(
                drivername="postgresql+psycopg_async",
                username="eval_app",
                password="disposable-app-only",
            )
            .render_as_string(hide_password=False)
        )
        inspection = create_engine(url)
        try:
            asyncio.run(execute(appurl, args.normalized, args.output, inspection))
        finally:
            inspection.dispose()


if __name__ == "__main__":
    main()
