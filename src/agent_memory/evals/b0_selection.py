"""Select IDs only from a hash-verified frozen dev corpus; never replace source text."""
from copy import deepcopy
from typing import Any

Corpus = list[dict[str, Any]]


def select_questions(
    corpus: Corpus,
    questions_by_conversation: dict[str, list[str]],
    *,
    quality_only: bool = False,
) -> Corpus:
    lookup = {row['conversation_id']: row for row in corpus}
    if len(lookup) != len(corpus) or not questions_by_conversation:
        raise ValueError('INVALID_DEV_SELECTION')
    selected = []
    for cid, wanted in questions_by_conversation.items():
        if cid not in lookup or not wanted or len(wanted) != len(set(wanted)):
            raise ValueError('NON_DEV_OR_DUPLICATE_SELECTION')
        original = lookup[cid]
        questions = {q['question_id']: q for q in original['questions']}
        if len(questions) != len(original['questions']) or not set(wanted) <= questions.keys():
            raise ValueError('QUESTION_NOT_IN_FROZEN_DEV_CONVERSATION')
        if quality_only:
            excluded = set(original.get('metadata', {}).get('flow_only_categories', []))
            if any(questions[qid]['category'] in excluded for qid in wanted):
                raise ValueError('FLOW_ONLY_QUESTION_NOT_QUALITY')
        row = deepcopy(original)
        row['questions'] = [q for q in original['questions'] if q['question_id'] in wanted]
        selected.append(row)
    return selected
