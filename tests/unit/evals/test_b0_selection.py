import pytest

from agent_memory.evals.b0_selection import select_questions


def corpus():
    return [{'conversation_id':'dev1','documents':[{'text':'immutable source'}],
             'metadata':{'flow_only_categories':['flow']},
             'questions':[{'question_id':'q1','category':'quality'}, {'question_id':'q2','category':'flow'}]}]


def test_selection_preserves_source_and_excludes_flow():
    source=corpus()
    result=select_questions(source,{'dev1':['q1']},quality_only=True)
    assert result[0]['documents']==source[0]['documents']
    assert len(source[0]['questions'])==2
    assert [q['question_id'] for q in result[0]['questions']]==['q1']
    for bad in [{'test1':['q1']},{'dev1':['test-q']},{'dev1':['q1','q1']},{'dev1':[]}]:
        with pytest.raises(ValueError):select_questions(source,bad)
    with pytest.raises(ValueError,match='FLOW_ONLY'):
        select_questions(source,{'dev1':['q2']},quality_only=True)
