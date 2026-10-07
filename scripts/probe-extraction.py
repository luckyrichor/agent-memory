"""Probe configured Ark extraction using synthetic content; never display credentials."""
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from agent_memory.domain.enums import ScopeKind
from agent_memory.domain.events import Event, EventDraft, EventType
from agent_memory.domain.models import MemoryScope
from agent_memory.infrastructure.llm_extractor import LLMExtractor


async def main() -> None:
    values = dict(line.split("=", 1) for line in Path(".local/ark.env").read_text()
                  .splitlines() if "=" in line and not line.startswith("#"))
    model = values.get("MEMORY_EXTRACTION_MODEL", "doubao-seed-2-0-lite-260428")
    extractor = LLMExtractor("https://ark.cn-beijing.volces.com/api/v3/chat/completions",
                             model, values["ARK_API_KEY"])
    now = datetime.now(UTC)
    event = Event(uuid4(), uuid4(), EventDraft("probe", "probe", 1, EventType.TOOL_RESULT,
        "probe", now, MemoryScope(ScopeKind.WORKSPACE, "synthetic-probe", None),
        {"summary": "Build failed because dependency architecture did not match target",
         "tool_name": "build", "exit_code": 1}), uuid4(), now)
    result = await extractor.extract(event)
    report = {"date": "2026-10-07", "model": model, "reason": extractor.last_reason,
              "candidates": len(result), "scope_preserved": all(c.scope == event.draft.scope for c in result),
              "real_model_extraction_passed": extractor.last_reason == "LLM_EXTRACTED"}
    Path("docs/measurements/w8-extraction-probe.json").write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps(report))


asyncio.run(main())
