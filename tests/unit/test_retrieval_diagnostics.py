from agent_memory.evals.datasets import Conversation, Document, Question
from agent_memory.evals.retrieval_diagnostics import audit_mapping, keyword_predictions


def fixture():
    return Conversation(
        conversation_id="fixture",
        documents=[
            Document(
                source_id="D1:1",
                session_id="s",
                role="source",
                text="Alice: I enjoy mountain hiking.",
            ),
            Document(
                source_id="D1:2", session_id="s", role="source", text="Bob: My laptop is repaired."
            ),
        ],
        questions=[
            Question(
                question_id="q",
                text="Where does Alice enjoy hiking?",
                answer="ignored",
                category="test",
                relevant={"D1:1": 1},
            )
        ],
    )


def test_baseline_uses_query_and_original_turns_never_reference_answer():
    conv = fixture()
    before = keyword_predictions(conv)
    after = keyword_predictions(
        conv.model_copy(
            update={
                "questions": [conv.questions[0].model_copy(update={"answer": "laptop repaired"})]
            }
        )
    )
    assert before == after
    assert before[0]["ranked_evidence_sets"][0] == ["D1:1"]


def test_mapping_audit_detects_missing_duplicate_and_unmapped_evidence():
    conv = fixture()
    mapping = [
        {"source_id": "D1:1", "part": 0, "version_id": "v1"},
        {"source_id": "D1:2", "part": 0, "version_id": "v2"},
    ]
    assert audit_mapping(conv, mapping)["chunk_mapping_bijective"]
    assert not audit_mapping(conv, mapping[:1])["chunk_mapping_bijective"]
    assert not audit_mapping(conv, mapping + mapping[:1])["chunk_mapping_bijective"]
    assert audit_mapping(conv, mapping[:1])["missing_source_ids"] == 1
