#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
uv sync --all-groups --frozen
uv run pytest -q
uv run ruff check src tests migrations
uv run mypy --strict src
uv run python -m agent_memory.evals.foundation_runner
