"""Conservative content gate; this is not a complete DLP system."""

import re
import unicodedata

_PATTERN = re.compile(
    r"(?i)(api[_ -]?key|password|passwd|secret|bearer|密码|密钥)"
    r"|(?:sk|ark|ghp|github_pat|xox[baprs])[-_][a-z0-9_-]{8,}"
    r"|AKIA[A-Z0-9]{16}|eyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+"
    r"|[\w.+-]+@[\w.-]+\.[a-z]{2,}|(?<!\d)1[3-9]\d{9}(?!\d)"
    r"|(?<!\d)\d{17}[\dXx](?!\d)|(?<!\d)(?:\d[ -]?){15,19}(?!\d)"
    r"|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"
)


def sensitive(text: str) -> bool:
    normalized = unicodedata.normalize("NFKC", text)
    normalized = "".join(c for c in normalized if unicodedata.category(c) != "Cf")
    return bool(_PATTERN.search(normalized))


def validate_content(text: str, *, max_length: int = 20000) -> None:
    from agent_memory.domain.errors import ContentRejected

    if not text.strip() or len(text) > max_length or sensitive(text):
        raise ContentRejected("CONTENT_POLICY_REJECTED")
