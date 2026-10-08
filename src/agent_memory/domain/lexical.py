"""Chinese bigrams and Latin words; mirrored by the migration's SQL function."""

import re


def lexical_tokens(text: str) -> set[str]:
    if not re.search(r"[一-鿿]", text):
        return set(re.findall(r"\w+", text.lower()))
    tokens: set[str] = set()
    for word in re.findall(r"[一-鿿]+|[a-z0-9_]+", text.lower()):
        if re.search(r"[一-鿿]", word) and len(word) > 1:
            tokens.update(word[i : i + 2] for i in range(len(word) - 1))
        else:
            tokens.add(word)
    return tokens
