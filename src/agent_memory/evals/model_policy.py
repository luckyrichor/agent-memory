"""Observed response checks shared by qualification and production annotation."""

from typing import Any


def require_disabled_thinking(data: dict[str, Any]) -> None:
    """Request acceptance alone does not prove the provider disabled reasoning."""
    message = data["choices"][0]["message"]
    reasoning = message.get("reasoning_content")
    details = (data.get("usage") or {}).get("completion_tokens_details") or {}
    tokens = details.get("reasoning_tokens")
    if reasoning or (isinstance(tokens, (int, float)) and tokens > 0):
        raise RuntimeError("provider returned reasoning despite frozen disabled-thinking policy")
