"""Conservative lexical evidence gate; no inferred user facts or model/human labels."""

import re
from dataclasses import asdict, dataclass
from typing import Any

# Closed grammatical/relationship aliases, never an open-ended semantic paraphraser.
ALIASES = (
    ("想成为", "想当"),
    ("是一名", "是"),
    ("是一个", "是"),
    ("母亲", "妈妈"),
    ("父亲", "爸爸"),
    ("女儿", "闺女"),
    ("丈夫", "老公"),
    ("妻子", "老婆"),
    ("我们家", "我家"),
)
OWNER = re.compile(
    r"^我(?:的)?(妈妈|爸爸|闺女|儿子|孩子|老公|老婆|哥哥|姐姐|弟弟|妹妹|朋友|同事|同学|邻居|老师|家人|父母|狗|猫)"
)
NEGATION = re.compile(r"不|没|未|无|并非|不是|否认|假如|如果|假设|也许|可能")
QUALIFIERS = re.compile(
    r"最(?:喜欢|爱)|轻度|中度|重度|被诊断|诊断|每天|每周|每月|每年|每个周末|周末|刚刚|刚|今年|去年|大学|订婚|结婚|整天|总是|所有|全部|[0-9一二三四五六七八九十两]+(?:年|月|日|岁|个|次|小时)"
)
VERSION = "verbatim-v1"


def normalize(text: str) -> str:
    for a, b in ALIASES:
        text = text.replace(a, b)
    # Only orthography and closed grammatical particles are ignored; no degree,
    # frequency, date, quantity, diagnosis, negation or named entity is deleted.
    return re.sub(r"[\s\W的了是]", "", text)


@dataclass(frozen=True)
class Decision:
    status: str
    reasons: tuple[str, ...]
    evidence: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def align(needle: str, haystack: str) -> tuple[int, int] | None:
    cursor = 0
    positions = []
    for char in needle:
        pos = haystack.find(char, cursor)
        if pos < 0:
            return None
        positions.append(pos)
        cursor = pos + 1
    return (positions[0], positions[-1] + 1) if positions else None


def check_strict_candidate(row: dict[str, Any]) -> Decision:
    claim = re.sub(r"^(?:用户陈述|当前用户陈述)[：:]", "", row["candidate"]).strip()
    atoms = [p.strip() for p in re.split(r"[，,。；;]", claim) if p.strip()]
    if not atoms:
        return Decision("uncertain", ("EMPTY_CLAIM",), ())
    evidence = []
    for atom in atoms:
        # Omitted subject in a conjunct retains the candidate's user subject;
        # it must still be evidenced by the user's own explicit first-person clause.
        full = atom if atom.startswith("我") else "我" + atom
        canonical = normalize(full)
        candidate_owner = OWNER.match(canonical)
        matched = False
        for document in row["source"]:
            if document.get("role") != "user":
                continue
            for part in re.finditer(r"([^。！？!?；;]+)([。！？!?；;]|$)", document["text"]):
                text, terminator = part.groups()
                # Questions are not assertions; plain acknowledgement never supplies
                # a predicate/object missing from the user's own utterance.
                if terminator in ("?", "？") or any(c in text for c in ("“", "”", "「", "」", '"')):
                    continue
                if re.match(r"我(?:是|为|当|做)(?:一名|一个)?", full) and not re.search(
                    r"我(?:(?:现在|目前|曾经|以前|已经|今年|还|也|就|本来|其实|一直|就是){0,3})(?:是|为|当|做)",
                    text,
                ):
                    continue
                if full.startswith("我叫") and not re.search(r"我(?:的名字)?叫", text):
                    continue
                normalized = normalize(text)
                if "我" not in normalized:
                    continue
                start = normalized.find("我")
                source_owner = OWNER.match(normalized[start:])
                if bool(candidate_owner) != bool(source_owner):
                    continue
                if candidate_owner and source_owner and candidate_owner[1] != source_owner[1]:
                    continue
                alignment = align(canonical, normalized[start:])
                if alignment is None:
                    continue
                witness = normalized[start:][alignment[0] : alignment[1]]
                if NEGATION.search(witness):
                    continue
                if re.search(r"(?:他说|她说|朋友说|同事说|据说|听说|告诉我)", text):
                    continue
                if re.search(r"(?:他|她|朋友|同事).{0,4}(?:喜欢|偏好|是|住|叫)", witness):
                    continue
                if any(normalize(q) not in normalized for q in QUALIFIERS.findall(full)):
                    continue
                # Critical predicate atoms are contiguous, not collected character by
                # character from unrelated words or from another speaker.
                predicates = re.findall(
                    r"最喜欢|喜欢|爱好|偏好|想当|诊断|订婚|结婚|住在|工作|毕业|叫", canonical
                )
                if any(p not in witness for p in predicates):
                    continue
                evidence.append(
                    {
                        "source_id": document["source_id"],
                        "role": "user",
                        "candidate_atom": atom,
                        "canonical_candidate": canonical,
                        "canonical_witness": witness,
                        "source_text": text,
                        "check": "all canonical detail characters present in order; critical predicates/qualifiers contiguous",
                    }
                )
                matched = True
                break
            if matched:
                break
        if not matched:
            return Decision("uncertain", ("NO_LITERAL_SELF_EVIDENCE",), tuple(evidence))
    return Decision("supported", (), tuple(evidence))


# The strict alignment prototype is retained for comparison. The detail-level
# proposal below permits reordered literal details, never arbitrary paraphrases.
VERSION = "verbatim-v2-detail-atoms"
SINGLE_GRAMMAR = set("我的是了在有来去和到着住叫想当做开看里家个")


def literal_atoms(candidate: str, source: str) -> list[str] | None:
    """Cover every non-grammar character using exact contiguous source fragments.

    Arbitrary one-character matches cannot manufacture an absent noun/detail.
    Degree/date/diagnosis atoms are checked as complete atoms by the caller.
    """
    states: dict[int, list[str]] = {0: []}
    for i in range(len(candidate)):
        if i not in states:
            continue
        if candidate[i] in "我的了是":
            states.setdefault(i + 1, states[i])
        for end in range(len(candidate), i, -1):
            fragment = candidate[i:end]
            if fragment not in source:
                continue
            if len(fragment) == 1 and fragment not in SINGLE_GRAMMAR:
                continue
            states.setdefault(end, [*states[i], fragment])
    return states.get(len(candidate))


def user_windows(text: str) -> list[tuple[str, str]]:
    windows = []
    for match in re.finditer(r"([^。！？!?；;]+)([。！？!?；;]|$)", text):
        sentence, end = match.groups()
        if end in ("?", "？") and re.search(r"吗|是否|是不是|还是|能否", sentence):
            continue
        clauses = re.split(r"[，,]", sentence)
        for i in range(len(clauses)):
            for width in (1,):
                if i + width <= len(clauses):
                    last = end if i + width == len(clauses) else "，"
                    windows.append(("，".join(clauses[i : i + width]), last))
    return windows


def check_candidate(row: dict[str, Any]) -> Decision:
    claim = re.sub(r"^(?:用户陈述|当前用户陈述)[：:]", "", row["candidate"]).strip()
    atoms = [p.strip() for p in re.split(r"[，,。；;]", claim) if p.strip()]
    if not atoms:
        return Decision("uncertain", ("EMPTY_CLAIM",), ())
    evidence = []
    for atom in atoms:
        full = atom if atom.startswith("我") else "我" + atom
        canonical = normalize(full)
        matched = False
        for document in row["source"]:
            if document.get("role") != "user":
                continue
            for text, terminator in user_windows(document["text"]):
                if terminator in ("?", "？") or any(c in text for c in ("“", "”", "「", "」", '"')):
                    continue
                if "我" not in text or re.search(r"他说|她说|朋友说|同事说|听说|告诉我", text):
                    continue
                if re.search(r"不|没|未|无|假如|如果|假设|也许|可能", text):
                    continue
                normalized = normalize(text)
                candidate_owner = OWNER.match(canonical)
                source_owner = OWNER.match(normalized[normalized.find("我") :])
                if bool(candidate_owner) != bool(source_owner):
                    continue
                if candidate_owner and source_owner and candidate_owner[1] != source_owner[1]:
                    continue
                if full.startswith(("我是", "我为", "我当", "我做")) and not re.search(
                    r"我(?:(?:现在|目前|曾经|以前|已经|今年|还|也|就|本来|其实|一直|就是){0,3})(?:是|为|当|做)",
                    text,
                ):
                    continue
                if full.startswith("我叫") and not re.search(r"我(?:的名字)?叫", text):
                    continue
                # Preferences require the USER to state a preference, not merely
                # perform an activity or agree with the assistant's suggestion.
                if re.search(r"喜欢|偏好|爱好|最爱|热爱", full) and not re.search(
                    r"我(?:(?:就|也|还|更|最|比较|一直|平时|非常|特别|很|真|是){0,4})(?:喜欢|偏好|爱好|爱|热爱)|我的爱好",
                    text,
                ):
                    continue
                if any(normalize(q) not in normalized for q in QUALIFIERS.findall(full)):
                    continue
                fragments = literal_atoms(canonical, normalized)
                if fragments is None:
                    continue
                evidence.append(
                    {
                        "source_id": document["source_id"],
                        "role": "user",
                        "candidate_atom": atom,
                        "literal_fragments": fragments,
                        "source_text": text,
                        "check": "exact source fragments cover all non-grammar content; qualifiers/subject/predicate separately checked",
                    }
                )
                matched = True
                break
            if matched:
                break
        if not matched:
            return Decision("uncertain", ("DETAIL_OR_SELF_PREDICATE_UNSUPPORTED",), tuple(evidence))
    return Decision("supported", (), tuple(evidence))
