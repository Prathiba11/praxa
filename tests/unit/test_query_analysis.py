"""Query analysis: JSON parsing, filter construction, and graceful degradation."""

from unittest.mock import patch

from career_copilot.core.errors import LLMError
from career_copilot.core.llm import ChatResult
from career_copilot.core.types import DocType, Profile
from career_copilot.rag.query_analysis import (
    SYSTEM_PROMPT,
    Intent,
    QueryAnalysis,
    analyse_query,
)

VALID = """{"intent":"kb_question","profiles":["devops"],"doc_types":["resume"],
"keywords":["Kubernetes"],"location":null,"posted_since_days":null,"confidence":0.85}"""


def _result(content: str) -> ChatResult:
    return ChatResult(
        content=content,
        tool_calls=[],
        model="test/model",
        finish_reason="stop",
        prompt_tokens=10,
        completion_tokens=5,
        latency_ms=1.0,
    )


def _patched(content: str):
    return patch("career_copilot.rag.query_analysis.chat", return_value=_result(content))


# ---------------------------------------------------------------- parsing


def test_valid_response_is_parsed():
    with _patched(VALID):
        analysis = analyse_query("what Kubernetes experience do I have?")

    assert analysis.intent == Intent.KB_QUESTION
    assert analysis.profiles == [Profile.DEVOPS]
    assert analysis.doc_types == [DocType.RESUME]
    assert analysis.confidence == 0.85


def test_json_wrapped_in_a_code_fence_is_parsed():
    """Models often wrap JSON despite being told not to."""
    with _patched(f"Here you go:\n```json\n{VALID}\n```\nHope that helps."):
        analysis = analyse_query("anything")
    assert analysis.profiles == [Profile.DEVOPS]


def test_out_of_domain_intent_is_recognised():
    payload = (
        '{"intent":"out_of_domain","profiles":[],"doc_types":[],"keywords":[],'
        '"location":null,"posted_since_days":null,"confidence":0.95}'
    )
    with _patched(payload):
        assert analyse_query("what is the weather?").intent == Intent.OUT_OF_DOMAIN


def test_a_bare_domain_question_is_in_scope():
    """ "What is DevOps" is a question this assistant answers.

    It has no "I" or "my" in it and it is not a job search, and the classifier
    used to drop it into out_of_domain for exactly that reason - then refused it
    with a sentence naming DevOps as covered, without ever searching the DevOps
    notes sitting in the knowledge base. The prompt now says bare domain
    questions are kb_question; this pins the parsing side of that.
    """
    payload = (
        '{"intent":"kb_question","profiles":["devops"],"doc_types":["domain"],'
        '"keywords":["DevOps","CI/CD"],"location":null,"posted_since_days":null,'
        '"confidence":0.7}'
    )
    with _patched(payload):
        analysis = analyse_query("what is DevOps?")

    assert analysis.intent == Intent.KB_QUESTION
    assert analysis.doc_types == [DocType.DOMAIN]


def test_the_prompt_states_that_bare_domain_questions_are_in_scope():
    """A guard on the instruction itself.

    Whether the model obeys it needs a live call, and that lives in the `live`
    suite. What is worth pinning here is that the rule has not been deleted:
    without it the classifier reverts to refusing "what is DevOps", and nothing
    else in the suite would notice.
    """
    lowered = SYSTEM_PROMPT.lower()
    assert "what is devops" in lowered, "the worked example for a bare domain question is gone"
    assert "kb_question" in lowered
    assert "lower your confidence" in lowered, "the tie-break rule is gone"


# ---------------------------------------------------------------- degradation


def test_llm_failure_degrades_to_unfiltered_search():
    """Analysis improves retrieval; it must never prevent it."""
    with patch("career_copilot.rag.query_analysis.chat", side_effect=LLMError("upstream down")):
        analysis = analyse_query("what Kubernetes experience do I have?")

    assert analysis.confidence == 0.0
    assert analysis.where() is None


def test_malformed_json_degrades_rather_than_raising():
    with _patched("I'm afraid I can't do that."):
        analysis = analyse_query("anything")
    assert analysis.where() is None


def test_unknown_enum_value_degrades():
    """An invented profile name must not reach Chroma as a filter."""
    with _patched('{"intent":"kb_question","profiles":["quantum_computing"],"doc_types":[]}'):
        analysis = analyse_query("anything")
    assert analysis.where() is None


# ---------------------------------------------------------------- filters


def test_no_constraints_means_no_filter():
    assert QueryAnalysis().where() is None


def test_profiles_only():
    where = QueryAnalysis(profiles=[Profile.DEVOPS]).where()
    assert where == {"profile": {"$in": ["devops"]}}


def test_doc_types_only():
    where = QueryAnalysis(doc_types=[DocType.GUIDE]).where()
    assert where == {"doc_type": {"$in": ["guide"]}}


def test_both_are_combined_with_and():
    where = QueryAnalysis(
        profiles=[Profile.DEVOPS, Profile.AI_ENG], doc_types=[DocType.RESUME]
    ).where()

    assert where is not None
    assert "$and" in where
    assert {"profile": {"$in": ["devops", "ai_eng"]}} in where["$and"]
    assert {"doc_type": {"$in": ["resume"]}} in where["$and"]
