"""Refresh both catalogs and preflight a bounded, explicit independent-vendor roster."""

import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path
import httpx
from agent_memory.evals import model_preflight

OUT = Path(".local/phase1/round3/owner-hardset/judge-discovery")


async def main():
    OUT.mkdir(parents=True, exist_ok=False, mode=0o700)
    catalogs = {}
    async with httpx.AsyncClient(timeout=45, trust_env=False) as client:
        for provider, base, key in [
            ("Ark", "https://ark.cn-beijing.volces.com/api/v3", os.environ["ARK_API_KEY"]),
            (
                "TokenHub",
                os.getenv("TENCENT_BASE_URL", "https://tokenhub.tencentmaas.com/v1"),
                os.getenv("TOKENHUB_API_KEY") or os.environ["TENCENT_API_KEY"],
            ),
        ]:
            r = await client.get(
                base.rstrip("/") + "/models", headers={"Authorization": "Bearer " + key}
            )
            ids = [x["id"] for x in r.json().get("data", [])] if r.is_success else []
            catalogs[provider] = {
                "http_status": r.status_code,
                "models": ids,
                "at": datetime.now(UTC).isoformat(),
            }
    (OUT / "catalogs.json").write_text(json.dumps(catalogs, indent=2))
    roster = [
        ("Ark", "qwen3-14b-20250429"),
        ("Ark", "qwen2-5-72b-20240919"),
        ("TokenHub", "glm-5.2"),
        ("TokenHub", "minimax-m3"),
    ]
    for provider, model in roster:
        if model not in catalogs[provider]["models"]:
            continue
        if provider == "Ark":
            model_preflight.ARK_MODELS = (*model_preflight.ARK_MODELS, model)
        await model_preflight.run(
            OUT / (provider + "-" + model),
            Path("docs/evals/prompts/preflight-v1.txt"),
            models=(model,),
            interval=0.6,
        )
    print(
        json.dumps(
            {
                "catalog_counts": {p: len(v["models"]) for p, v in catalogs.items()},
                "output": str(OUT),
            }
        )
    )


asyncio.run(main())
