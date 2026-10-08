"""Conservative content gate; this is not a complete DLP system."""

import re
import unicodedata

_PATTERN = re.compile(
    r"(?i)(?P<secret>(?<!\w)(?:api[_ -]?key|password|passwd|secret)(?!\w)"
    r"\s*[\"']?\s*[:=]\s*[\"']?\S+|\bBearer\s+[a-z0-9._-]{8,}"
    r"|(?:密码|密钥)(?:\s*[:=：]\s*|\s+)\S+)"
    r"|(?:sk|ark|ghp|github_pat|xox[baprs])[-_][a-z0-9_-]{8,}"
    r"|AKIA[A-Z0-9]{16}|eyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+"
    r"|[\w.+-]+@[\w.-]+\.[a-z]{2,}"
    r"|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"
)


_NUMERIC_PATTERN = re.compile(
    r"(?<!\d)1[3-9]\d{9}(?!\d)|(?<!\d)\d{17}[\dXx](?!\d)"
    r"|(?<!\d)(?:\d[ -]?){15,19}(?!\d)"
)
_UUID_PATTERN = re.compile(
    r"(?<![\w-])[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(?![\w-])",
    re.IGNORECASE,
)


def sensitive(text: str) -> bool:
    normalized = unicodedata.normalize("NFKC", text)
    normalized = "".join(c for c in normalized if unicodedata.category(c) != "Cf")
    # UUID identifiers are not account numbers. Only numeric detection ignores them;
    # token/keyword/email checks still see the complete original content.
    numeric_text = _UUID_PATTERN.sub("UUID", normalized)
    return bool(_PATTERN.search(normalized) or _NUMERIC_PATTERN.search(numeric_text))


def validate_content(text: str, *, max_length: int = 20000) -> None:
    from agent_memory.domain.errors import ContentRejected

    if not text.strip():
        raise ContentRejected("CONTENT_EMPTY")
    if len(text) > max_length:
        raise ContentRejected("CONTENT_TOO_LONG")
    if sensitive(text):
        normalized = unicodedata.normalize("NFKC", text)
        normalized = "".join(c for c in normalized if unicodedata.category(c) != "Cf")
        match = _PATTERN.search(normalized)
        reason = (
            "CONTENT_SECRET_VALUE"
            if match and match.lastgroup == "secret"
            else "CONTENT_TOKEN_OR_CONTACT"
            if match
            else "CONTENT_NUMERIC_IDENTIFIER"
        )
        raise ContentRejected(reason)
