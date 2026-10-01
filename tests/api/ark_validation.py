"""Opt-in paid Ark validation: explicitly run this file with MEMORY_EMBEDDING_* set.

Not part of offline pytest discovery; uses an isolated Testcontainers database.
Only synthetic corpus is sent to the provider, never existing user memories.
"""
import asyncio
import hashlib
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx
import jwt
import pytest
from test_memory_api import bearer_token, signing_material

from agent_memory.api.app import create_app
from agent_memory.application.embedding import EmbeddingWorker
from agent_memory.config import Settings
from agent_memory.infrastructure.db import create_session_factory
from agent_memory.infrastructure.embedding import HTTPEmbeddingProvider, PostgresEmbeddingBackend

CORPUS = [
    ("这个项目采用 Java 17 作为运行环境。", "应用应该安装哪个版本的JDK？"),
    ("用户不吃花生，食用花生会引发过敏。", "推荐零食时需要避开什么食材？"),
    ("服务发布失败时先回退到上一稳定版本，再排查日志。", "上线出错以后应该如何应急处理？"),
    ("会议固定在每周三下午两点召开。", "团队例会安排在什么时候？"),
    ("公司报销需要提供发票和支付凭证。", "申请费用返还要准备哪些材料？"),
]


@pytest.mark.asyncio
async def test_real_ark_paraphrase_worker_postgres_api_and_isolation(app_database_url):
    private, public = signing_material()
    settings = Settings(database_url=app_database_url, jwt_public_key=public,
        jwt_issuer="memory-test", jwt_audience="memory-api",
        embedding_endpoint=os.environ["MEMORY_EMBEDDING_ENDPOINT"],
        embedding_model=os.environ["MEMORY_EMBEDDING_MODEL"],
        embedding_token=os.environ["MEMORY_EMBEDDING_TOKEN"],
        embedding_protocol="ark", embedding_trust_env=False)
    app = create_app(settings)
    tenant = uuid4()
    claims = jwt.decode(bearer_token(private), options={"verify_signature": False})
    claims["tenant_id"] = str(tenant)
    headers = {"Authorization": "Bearer " + jwt.encode(claims, private, algorithm="RS256")}
    records, observations = [], []
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                     base_url="http://test") as client:
            for content, _ in CORPUS:
                response = await client.post("/v1/memories", headers={**headers,
                    "Idempotency-Key": str(uuid4())}, json={"content": content,
                    "memory_type": "semantic", "scope": {"kind": "workspace",
                    "workspace_id": "project-a"}})
                assert response.status_code == 201
                records.append(response.json())
            async with httpx.AsyncClient(timeout=10, trust_env=False) as upstream:
                provider = HTTPEmbeddingProvider(upstream, endpoint=settings.embedding_endpoint,
                    model=settings.embedding_model, token=settings.embedding_token.get_secret_value(),
                    protocol="ark")
                backend = PostgresEmbeddingBackend(create_session_factory(app.state.engine))
                worker = EmbeddingWorker(backend, provider)
                for _ in records:
                    assert (await worker.run_once(tenant, "ark-validation")).outcome == "succeeded"
                assert (await worker.run_once(tenant, "ark-validation")).outcome == "no_job"
            for index, (_, query) in enumerate(CORPUS):
                response = await client.post("/v1/memories/search", headers=headers,
                    json={"query": query, "limit": 3})
                assert response.status_code == 200
                page = response.json()
                assert page["vector_status"] == "provider"
                correct = page["items"][0]["memory_id"] == records[index]["memory_id"]
                observations.append({"case": index + 1, "top1_correct": correct,
                    "channel_counts": page["channel_counts"],
                    "top1_ranks": page["items"][0]["ranks"]})
            other_claims = {**claims, "tenant_id": str(uuid4())}
            other_headers = {"Authorization": "Bearer " +
                jwt.encode(other_claims, private, algorithm="RS256")}
            other = await client.post("/v1/memories/search", headers=other_headers,
                json={"query": CORPUS[0][1]})
            assert other.status_code == 200 and other.json()["items"] == []
            deletion = await client.post("/v1/deletion-requests", headers={**headers,
                "Idempotency-Key": str(uuid4())}, json={"memory_id": records[0]["memory_id"],
                "expected_revision": 1})
            assert deletion.status_code == 202
            after = await client.post("/v1/memories/search", headers=headers,
                                      json={"query": CORPUS[0][1]})
            assert after.status_code == 200
            assert all(hit["memory_id"] != records[0]["memory_id"]
                       for hit in after.json()["items"])
            report = {"generated_at": datetime.now(UTC).isoformat(),
                "source_head": (await asyncio.to_thread(subprocess.check_output,
                    ["git", "rev-parse", "HEAD"], text=True)).strip(),
                "uncommitted": bool(await asyncio.to_thread(subprocess.check_output,
                    ["git", "status", "--porcelain"])),
                "source_sha256": {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                    for root in (Path("src"), Path("migrations")) for p in root.rglob("*.py")},
                "model": settings.embedding_model, "dimensions": 1024,
                "corpus_size": len(CORPUS), "queries": len(CORPUS),
                "top1_correct": sum(item["top1_correct"] for item in observations),
                "observations": observations, "tenant_leaks": 0, "deleted_hits": 0,
                "boundary": "synthetic five-case smoke, not production quality estimate"}
            output = Path("docs/measurements/2026-10-02-ark-retrieval.json")
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(report, indent=2) + "\n")
            assert report["top1_correct"] == len(CORPUS)
    finally:
        await app.state.engine.dispose()
