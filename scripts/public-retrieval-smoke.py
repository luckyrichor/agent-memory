"""Disposable PostgreSQL + public API smoke; NOT steady-state capacity or full B0."""

import argparse
import asyncio
import json
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
from agent_memory.evals.runner import save_report
from agent_memory.sdk import MemoryClient


async def execute(database_url, normalized, output):
    tenant, user = uuid4(), uuid4()
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = (
        key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    chosen = []
    for dataset in ["longmemeval_oracle", "locomo", "perltqa_zh"]:
        split = json.loads((normalized / f"{dataset}-split.json").read_text())
        dev = set(split["dev"])
        with (normalized / f"{dataset}.jsonl").open() as stream:
            for line in stream:
                conv = Conversation.model_validate_json(line)
                if conv.conversation_id in dev and conv.questions:
                    chosen.append((dataset, conv))
                    break
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
            "exp": datetime.now(UTC) + timedelta(minutes=30),
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
                folder.mkdir()
                source = folder / "dataset-local.jsonl"
                source.write_text(conv.model_dump_json() + "\n")
                mapping = await import_conversation(
                    sdk, conv, MemoryScope(ScopeKind.WORKSPACE, workspace, None), mode="direct"
                )
                predictions = await retrieve_sources(sdk, conv, mapping, workspace_id=workspace)
                mappingfile = folder / "mapping.json"
                mappingfile.write_text(json.dumps(mapping, indent=2))
                predfile = folder / "predictions.jsonl"
                predfile.write_text("".join(json.dumps(p) + "\n" for p in predictions))
                config = folder / "config.json"
                config.write_text(
                    json.dumps(
                        {
                            "channel": "PostgreSQL lexical+structured; vector unconfigured",
                            "transport": "in-process ASGI + actual PostgreSQL non-owner RLS",
                            "normalized_corpus_sha256": file_hash(normalized / f"{dataset}.jsonl"),
                            "subset": "first conversation with questions in seeded development split",
                            "full_corpus": False,
                            "model_calls": 0,
                            "mapping_records": len(mapping),
                        }
                    )
                )
                save_report(
                    folder / "report",
                    source,
                    predfile,
                    config,
                    "direct",
                    {"RT1", "RT2", "RT3", "RT4", "RT5", "RT6"},
                )
                print(dataset, "imported", len(mapping), "questions", len(predictions), flush=True)
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
        asyncio.run(execute(appurl, args.normalized, args.output))


if __name__ == "__main__":
    main()
