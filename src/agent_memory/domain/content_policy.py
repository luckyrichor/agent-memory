"""Conservative content gate; this is not a complete DLP system."""

import re
import unicodedata

_PATTERN = re.compile(
    r"(?i)(api[_ -]?key|password|passwd|secret|bearer|密码|密钥)"
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

    if not text.strip() or len(text) > max_length or sensitive(text):
        raise ContentRejected("CONTENT_POLICY_REJECTED")
