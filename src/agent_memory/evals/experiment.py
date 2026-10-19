"""One command: normalized corpus -> public API import -> search -> immutable report.

The service/dispatch/extraction/embedding workers must already be configured.
No production deployment, model switch or memory promotion is done by this tool.
"""

import argparse
import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from agent_memory.domain.enums import ScopeKind
from agent_memory.domain.models import MemoryScope
from agent_memory.domain.principal import RequestPrincipal
from agent_memory.evals.api_import import import_conversation, retrieve_sources
from agent_memory.evals.datasets import Conversation
from agent_memory.evals.evidence_observer import observe_versions
from agent_memory.evals.runner import SUPPORTED, save_report
from agent_memory.infrastructure.db import (
    create_engine,
    create_session_factory,
    session_for_principal,
)
from agent_memory.infrastructure.orm import JobRow
from agent_memory.sdk import MemoryClient


class SystemConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    base_url: str
    token_env: str = "MEMORY_EVAL_TOKEN"
    workspaces: dict[str, str]
    # Full-mode lineage is an internal measurement, using a non-owner connection.
    tenant_id: UUID | None = None
    observer_user_id: UUID | None = None
    database_url_env: str = "MEMORY_EVAL_DATABASE_URL"
    extractor_version: str | None = None
    worker_wait_seconds: float = Field(default=120, gt=0, le=3600)
    poll_seconds: float = Field(default=2, gt=0)


async def full_lineage(
    config: SystemConfig, mapping: list[dict[str, Any]], workspace: str
) -> list[dict[str, Any]]:
    if config.tenant_id is None or config.observer_user_id is None or not config.extractor_version:
        raise ValueError("full mode needs observer identity and exact extractor version")
    url = os.environ.get(config.database_url_env)
    if not url:
        raise ValueError("full mode observer database environment not configured")
    principal = RequestPrincipal(
        config.tenant_id, config.observer_user_id, frozenset(), frozenset(), frozenset({workspace})
    )
    engine = create_engine(url)
    sessions = create_session_factory(engine)
    event_ids = {str(row["event_id"]) for row in mapping}
    deadline = time.monotonic() + config.worker_wait_seconds
    try:
        while True:
            async with session_for_principal(sessions, principal) as session:
                # Check role before reading internal evaluation observations.
                versions = await observe_versions(session, mapping, tenant_id=config.tenant_id)
                jobs = list(
                    (
                        await session.scalars(
                            select(JobRow).where(
                                JobRow.tenant_id == config.tenant_id,
                                JobRow.job_type == "extract_event",
                                JobRow.payload["event_id"].astext.in_(event_ids),
                                JobRow.payload["extractor_version"].astext
                                == config.extractor_version,
                            )
                        )
                    ).all()
                )
                if any(job.status == "dead" for job in jobs):
                    raise ValueError(
                        "full import has dead extraction jobs; not scored as retrieval error"
                    )
                if len(jobs) == len(event_ids) and all(job.status == "succeeded" for job in jobs):
                    return versions
            if time.monotonic() >= deadline:
                raise TimeoutError("full import still pending; no quality score emitted")
            await asyncio.sleep(config.poll_seconds)
    finally:
        await engine.dispose()


async def execute(
    dataset: Path, config_path: Path, output: Path, mode: str, metrics: set[str]
) -> None:
    if metrics - SUPPORTED:
        raise ValueError("requested observation adapter unavailable")
    config = SystemConfig.model_validate_json(config_path.read_text())
    conversations = [
        Conversation.model_validate_json(line)
        for line in dataset.read_text().splitlines()
        if line.strip()
    ]
    if not conversations or len({c.conversation_id for c in conversations}) != len(conversations):
        raise ValueError("dataset must contain unique nonempty conversations")
    if any(c.conversation_id not in config.workspaces for c in conversations):
        raise ValueError("every conversation needs an explicitly authorized dedicated workspace")
    spaces = [config.workspaces[c.conversation_id] for c in conversations]
    if len(set(spaces)) != len(spaces):
        raise ValueError("conversations cannot share a workspace; would mix unrelated histories")
    token = os.environ.get(config.token_env)
    if not token:
        raise ValueError("API token environment not configured")
    output.mkdir(parents=True, exist_ok=False)
    output.chmod(0o700)
    predictions = output / "predictions.jsonl"
    mappingfile = output / "mapping.jsonl"
    async with httpx.AsyncClient(base_url=config.base_url, timeout=60, trust_env=False) as http:
        client = MemoryClient(http, token=token)
        with predictions.open("w") as stream, mappingfile.open("w") as mapstream:
            for conv, workspace in zip(conversations, spaces, strict=True):
                mapping = await import_conversation(
                    client, conv, MemoryScope(ScopeKind.WORKSPACE, workspace, None), mode=mode
                )
                if mode == "full":
                    mapping = await full_lineage(config, mapping, workspace)
                for row in mapping:
                    mapstream.write(json.dumps(row) + "\n")
                for result in await retrieve_sources(client, conv, mapping, workspace_id=workspace):
                    stream.write(json.dumps(result) + "\n")
    save_report(output / "report", dataset, predictions, config_path, mode, metrics)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--mode", choices=("direct", "full"), required=True)
    parser.add_argument("--metrics", default="RT1,RT2,RT3,RT4,RT5,RT6")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if ".local" not in args.output.resolve().parts:
        parser.error("live experiment artifacts belong in ignored .local/")
    asyncio.run(
        execute(args.dataset, args.config, args.output, args.mode, set(args.metrics.split(",")))
    )


if __name__ == "__main__":
    main()
