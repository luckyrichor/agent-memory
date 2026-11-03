"""Exact-duplicate detection for extracted candidates (E2).

Two texts are the same memory when they are equal after Unicode NFKC, case folding and
whitespace collapsing. That is all: no punctuation stripping, no stemming, no paraphrase or
semantic matching. "Use uv" and "use  UV" are duplicates; "Use uv." is not.
"""

import hashlib
import unicodedata


def normalize_for_dedup(content: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", content).casefold().split())


def dedup_hash(content: str) -> str:
    """SHA-256 of the normalized text. It only narrows the search; callers compare the text."""
    return hashlib.sha256(normalize_for_dedup(content).encode()).hexdigest()
