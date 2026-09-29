"""Query translation: parsing, shape validation, dedupe, and HyDE gating."""

from unittest.mock import patch

from career_copilot.core.errors import LLMError
from career_copilot.core.llm import ChatResult
from career_copilot.rag.query_analysis import QueryAnalysis
from career_copilot.rag.translate import QueryPlan, expand_query

VALID = """{"paraphrases":["threat modelling background",
"Bedrohungsanalyse und Risikobewertung Erfahrung","TARA project experience"],
"step_back":"what does an automotive cybersecurity engineer do?"}"""


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
    return patch("career_copilot.rag.translate.chat", return_value=_result(content))


# ---------------------------------------------------------------- parsing


def test_paraphrases_and_step_back_are_parsed():
    with _patched(VALID):
        plan = expand_query("what threat modelling experience do I have?", use_hyde=False)

    assert len(plan.paraphrases) == 3
    assert plan.step_back is not None
    assert any("Bedrohungsanalyse" in p for p in plan.paraphrases)


def test_malformed_paraphrases_field_is_ignored():
    """The model can return anything; a wrong shape must not crash the pipeline."""
    with _patched('{"paraphrases":"not a list","step_back":42}'):
        plan = expand_query("anything", use_hyde=False)

    assert plan.paraphrases == []
    assert plan.step_back is None
    assert plan.search_queries() == ["anything"]


def test_llm_failure_leaves_only_the_original():
    with patch("career_copilot.rag.translate.chat", side_effect=LLMError("down")):
        plan = expand_query("what experience do I have?", use_hyde=False)

    assert plan.search_queries() == ["what experience do I have?"]


def test_at_most_four_paraphrases_are_kept():
    many = '{"paraphrases":["a","b","c","d","e","f"],"step_back":"g"}'
    with _patched(many):
        plan = expand_query("original", use_hyde=False)
    assert len(plan.paraphrases) == 4


# ---------------------------------------------------------------- query set


def test_original_query_always_ranks_first():
    plan = QueryPlan(original="first", paraphrases=["second"], step_back="third")
    assert plan.search_queries()[0] == "first"


def test_duplicates_are_removed_case_insensitively():
    plan = QueryPlan(original="Kubernetes probes", paraphrases=["kubernetes probes", "other"])
    assert plan.search_queries() == ["Kubernetes probes", "other"]


def test_labelled_marks_each_strategy():
    plan = QueryPlan(original="a", paraphrases=["b"], step_back="c", hyde="d")
    labels = [label for label, _ in plan.labelled()]
    assert labels == ["original", "paraphrase", "step-back", "hyde"]


# ---------------------------------------------------------------- hyde gating


def test_hyde_is_skipped_when_disabled():
    with _patched(VALID) as mocked:
        plan = expand_query("a reasonably long and specific question here", use_hyde=False)

    assert plan.hyde is None
    assert mocked.call_count == 1  # translation only, no second call


def test_hyde_runs_for_short_questions():
    """Short questions give the retriever least to work with."""
    passage = (
        "TARA is the threat analysis and risk assessment process defined in "
        "ISO/SAE 21434, covering asset identification through risk treatment."
    )
    with patch("career_copilot.rag.translate.chat") as mocked:
        mocked.side_effect = [_result(VALID), _result(passage)]
        plan = expand_query("TARA?")

    assert plan.hyde == passage
    assert mocked.call_count == 2


def test_hyde_runs_when_analysis_confidence_is_low():
    passage = (
        "A hypothetical passage long enough to be a useful search key rather "
        "than a refusal or a placeholder such as N/A."
    )
    with patch("career_copilot.rag.translate.chat") as mocked:
        mocked.side_effect = [_result(VALID), _result(passage)]
        plan = expand_query(
            "a longer question that would not otherwise trigger hyde at all",
            analysis=QueryAnalysis(confidence=0.2),
        )

    assert plan.hyde == passage


def test_short_hyde_output_is_discarded():
    """The model answered "N/A" to a weather question - not a useful search key."""
    with patch("career_copilot.rag.translate.chat") as mocked:
        mocked.side_effect = [_result(VALID), _result("N/A")]
        plan = expand_query("weather?")

    assert plan.hyde is None


def test_hyde_failure_does_not_break_the_plan():
    with patch("career_copilot.rag.translate.chat") as mocked:
        mocked.side_effect = [_result(VALID), LLMError("down")]
        plan = expand_query("TARA?")

    assert plan.hyde is None
    assert len(plan.paraphrases) == 3
