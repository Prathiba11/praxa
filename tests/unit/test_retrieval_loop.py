"""Retrieval as a loop rather than a step.

The behaviour under test is the agentic part: search, judge what came back,
and when it is poor, search again with a different query instead of answering
confidently from the wrong passages.

Everything expensive is stubbed. What matters here is the control flow - how
many rounds ran, which query each used, which set of passages the answer was
finally written from - not whether a real model grades well, which is the
evaluation suite's question.
"""

from __future__ import annotations

import pytest

from career_copilot.core.config import get_settings
from career_copilot.core.events import RetrievalEvent, use_sink
from career_copilot.rag import pipeline as pipeline_module
from career_copilot.rag.grader import EvidenceGrade
from career_copilot.rag.pipeline import Source, answer_question
from career_copilot.rag.query_analysis import Intent, QueryAnalysis
from career_copilot.rag.translate import QueryPlan

QUESTION = "what Kubernetes work have I done?"


def _source(index: int, text: str) -> Source:
    return Source(
        index=index,
        citation=f"doc.md#{index}",
        source="doc.md",
        section=None,
        score=0.9,
        found_by=["dense"],
        text=text,
    )


@pytest.fixture(autouse=True)
def _settings(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-test-not-a-real-key")
    monkeypatch.setenv("CC_MODEL", "openai/gpt-4o-mini")
    monkeypatch.setenv("CC_DATA_DIR", str(tmp_path))
    # Set rather than deleted: a deleted variable falls through to `.env`,
    # and a machine configured for one round would fail every test here.
    monkeypatch.setenv("CC_MAX_RETRIEVAL_ROUNDS", "2")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture()
def rig(monkeypatch):
    """Stubs for everything the loop calls, plus a record of what it did."""
    seen: dict[str, list] = {"queries": [], "prompts": []}

    monkeypatch.setattr(
        pipeline_module,
        "analyse_query",
        lambda *a, **k: QueryAnalysis(intent=Intent.KB_QUESTION, confidence=1.0),
    )

    def retrieve(query, **kwargs):
        seen["queries"].append(query)
        round_number = len(seen["queries"])
        sources = [_source(1, f"passage from round {round_number}")]
        return sources, kwargs["analysis"], QueryPlan(original=query, keywords=[]), 7

    monkeypatch.setattr(pipeline_module, "retrieve_context", retrieve)

    def answer(messages, **kwargs):
        seen["prompts"].append(messages[-1]["content"])

        class _Result:
            content = "Answered."
            prompt_tokens = 10
            completion_tokens = 5

        return _Result()

    monkeypatch.setattr(pipeline_module, "chat", answer)
    return seen


def _grades(monkeypatch, *grades: EvidenceGrade):
    """Script the grader: one verdict per round, in order."""
    queue = list(grades)

    def grade(*_args, **_kwargs):
        return queue.pop(0) if queue else grades[-1]

    monkeypatch.setattr(pipeline_module, "grade_evidence", grade)


# ------------------------------------------------------------- the easy case


def test_good_evidence_answers_after_one_round(monkeypatch, rig):
    """The common case must stay cheap: one search, one cheap grade, done."""
    _grades(monkeypatch, EvidenceGrade(verdict="sufficient", reason="covers it"))

    result = answer_question(QUESTION, session_id="s1")

    assert len(rig["queries"]) == 1
    assert len(result.trace.rounds) == 1
    assert result.trace.rounds[0].verdict == "sufficient"


# ---------------------------------------------------------------- the re-query


def test_weak_evidence_buys_a_second_search_with_a_different_query(monkeypatch, rig):
    _grades(
        monkeypatch,
        EvidenceGrade(verdict="weak", reason="thin", better_query="container orchestration"),
        EvidenceGrade(verdict="sufficient", reason="found it"),
    )

    result = answer_question(QUESTION, session_id="s1")

    assert rig["queries"] == [QUESTION, "container orchestration"]
    assert [r.verdict for r in result.trace.rounds] == ["weak", "sufficient"]


def test_the_answer_is_written_from_the_better_round(monkeypatch, rig):
    _grades(
        monkeypatch,
        EvidenceGrade(verdict="weak", reason="thin", better_query="try this"),
        EvidenceGrade(verdict="sufficient", reason="found it"),
    )

    answer_question(QUESTION, session_id="s1")

    assert "passage from round 2" in rig["prompts"][0]
    assert "passage from round 1" not in rig["prompts"][0]


def test_a_retry_that_came_back_worse_does_not_cost_us_the_first_round(monkeypatch, rig):
    """Keeping the last round instead of the best one would mean a failed
    experiment throws away the evidence we already had."""
    _grades(
        monkeypatch,
        EvidenceGrade(verdict="weak", reason="thin", better_query="try this"),
        EvidenceGrade(verdict="none", reason="that was worse"),
    )

    answer_question(QUESTION, session_id="s1")

    assert "passage from round 1" in rig["prompts"][0]


def test_a_weak_grade_with_nothing_else_to_try_stops(monkeypatch, rig):
    """Re-running the identical search would return the identical passages
    and bill for them."""
    _grades(monkeypatch, EvidenceGrade(verdict="weak", reason="thin", better_query=None))

    answer_question(QUESTION, session_id="s1")

    assert len(rig["queries"]) == 1


# ------------------------------------------------------------------- bounds


def test_the_loop_is_bounded_however_bad_the_evidence_is(monkeypatch, rig):
    """An agent that can keep searching is an agent that can keep billing."""
    _grades(monkeypatch, EvidenceGrade(verdict="none", reason="nope", better_query="again"))

    answer_question(QUESTION, session_id="s1")

    assert len(rig["queries"]) == get_settings().max_retrieval_rounds


def test_the_bound_is_configurable(monkeypatch, rig):
    monkeypatch.setenv("CC_MAX_RETRIEVAL_ROUNDS", "3")
    get_settings.cache_clear()
    _grades(monkeypatch, EvidenceGrade(verdict="none", reason="nope", better_query="again"))

    answer_question(QUESTION, session_id="s1")

    assert len(rig["queries"]) == 3


def test_one_round_turns_the_loop_off_without_removing_the_grade(monkeypatch, rig):
    """The A/B setting for the evaluation report: judge, but never re-query."""
    monkeypatch.setenv("CC_MAX_RETRIEVAL_ROUNDS", "1")
    get_settings.cache_clear()
    _grades(monkeypatch, EvidenceGrade(verdict="none", reason="nope", better_query="again"))

    result = answer_question(QUESTION, session_id="s1")

    assert len(rig["queries"]) == 1
    assert result.trace.rounds[0].verdict == "none"


# ------------------------------------------------------- telling the model


def test_a_poor_verdict_is_passed_to_the_model_writing_the_answer(monkeypatch, rig):
    """The failure being guarded against is a fluent paragraph written from
    passages that did not cover the question. The verdict has to reach the
    answer, not just the trace panel."""
    _grades(monkeypatch, EvidenceGrade(verdict="weak", reason="only mentions Docker"))

    answer_question(QUESTION, session_id="s1")

    assert "WEAK" in rig["prompts"][0]
    assert "only mentions Docker" in rig["prompts"][0]


def test_good_evidence_adds_nothing_to_the_prompt(monkeypatch, rig):
    _grades(monkeypatch, EvidenceGrade(verdict="sufficient", reason="covers it"))

    answer_question(QUESTION, session_id="s1")

    assert "NOTE: a relevance check" not in rig["prompts"][0]


def test_an_ungraded_answer_reads_as_it_did_before_the_grader_existed(monkeypatch, rig):
    """A grader that could not run must not make the answer hedge. It has no
    opinion, so it must not imply one."""
    _grades(
        monkeypatch,
        EvidenceGrade(verdict="sufficient", reason="grader unavailable", graded=False),
    )

    answer_question(QUESTION, session_id="s1")

    assert "NOTE: a relevance check" not in rig["prompts"][0]


# ------------------------------------------------------------------- events


def test_each_round_is_reported_as_it_happens(monkeypatch, rig):
    """This is what makes the loop visible in the UI while it runs, rather
    than asserted afterwards."""
    _grades(
        monkeypatch,
        EvidenceGrade(verdict="weak", reason="thin", better_query="second try"),
        EvidenceGrade(verdict="sufficient", reason="found it"),
    )
    events = []

    with use_sink(events.append):
        answer_question(QUESTION, session_id="s1")

    retrievals = [e for e in events if isinstance(e, RetrievalEvent)]
    assert [(e.round, e.verdict, e.query) for e in retrievals] == [
        (1, "weak", QUESTION),
        (2, "sufficient", "second try"),
    ]


def test_nothing_breaks_when_nobody_is_listening(monkeypatch, rig):
    """The pipeline is called from scripts and tests with no sink installed."""
    _grades(monkeypatch, EvidenceGrade(verdict="sufficient", reason="covers it"))

    assert answer_question(QUESTION, session_id="s1").answer == "Answered."


# -------------------------------------------------------------- the guardrail


def test_an_out_of_domain_question_never_reaches_the_loop(monkeypatch, rig):
    """The cheap refusal has to stay cheap: no retrieval, no grading."""
    monkeypatch.setattr(
        pipeline_module,
        "analyse_query",
        lambda *a, **k: QueryAnalysis(intent=Intent.OUT_OF_DOMAIN, confidence=1.0),
    )

    result = answer_question("what is the weather in Stuttgart?", session_id="s1")

    assert rig["queries"] == []
    assert result.trace.rounds == []
