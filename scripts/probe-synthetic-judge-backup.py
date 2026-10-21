"""Bounded retries of independent-vendor candidates; no quota/activation APIs."""

import asyncio
from pathlib import Path
from agent_memory.evals import model_preflight


async def main():
    root = Path(".local/phase1/round3/approved-followup/judge-probes")
    root.mkdir(parents=True, exist_ok=False, mode=0o700)
    for provider, model in [("TokenHub", "mimo-v2.6-pro"), ("Ark", "glm-4-5-air-20250728")]:
        if provider == "Ark":
            model_preflight.ARK_MODELS = (*model_preflight.ARK_MODELS, model)
        await model_preflight.run(
            root / (provider + "-" + model),
            Path("docs/evals/prompts/preflight-v1.txt"),
            models=(model,),
            interval=0.6,
        )


asyncio.run(main())
