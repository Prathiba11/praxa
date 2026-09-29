"""The transition rule.

This is the module that exists precisely so it can be tested, so it is tested
properly: every branch, both sides of the threshold, and the three independent
reasons the loop must terminate.
"""

from __future__ import annotations

import pytest

from career_copilot.core.types import Profile
from career_copilot.interview.engine import (
    DEFAULT_QUESTIONS,
    HARD_ANSWER_CAP,
    Move,
    Plan,
    decide_next,
    probe_question,
)
from career_copilot.interview.personas import Difficulty, get_persona, probe_threshold
from career_copilot.interview.rubric import MAX_SCORE, RubricScore


def _score(value: float = 4.0, **overrides: float) -> RubricScore:
    """A uniform score, with named dimensions pulled down where a test needs it."""
    base = dict.fromkeys(("structure", "specificity", "ownership", "impact", "relevance"), value)
    base.update(overrides)
    return RubricScore(**base)


def _plan(persona: str = "tech_lead", difficulty: Difficulty = Difficulty.STANDARD) -> Plan:
    return Plan(
        profile=Profile.DEVOPS,
        persona=get_persona(persona),
        difficulty=difficulty,
    )


# ------------------------------------------------------------------ probing


def test_a_weak_dimension_triggers_a_probe():
    plan = _plan()
    score = _score(5.0, specificity=0.5)
    move = decide_next(score, plan=plan, questions_asked=1, probes_used=0, answers_given=1)
    assert move is Move.PROBE


def test_a_strong_answer_moves_on():
    plan = _plan()
    move = decide_next(_score(5.0), plan=plan, questions_asked=1, probes_used=0, answers_given=1)
    assert move is Move.NEXT


def test_the_threshold_is_the_boundary_not_a_suggestion():
    """Just below probes, exactly on it does not. Stated as a test because a
    silent flip between < and <= changes how every session feels."""
    plan = _plan()
    threshold = plan.threshold

    below = decide_next(
        _score(5.0, impact=threshold - 0.01),
        plan=plan,
        questions_asked=1,
        probes_used=0,
        answers_given=1,
    )
    at = decide_next(
        _score(5.0, impact=threshold),
        plan=plan,
        questions_asked=1,
        probes_used=0,
        answers_given=1,
    )
    assert below is Move.PROBE
    assert at is Move.NEXT


def test_only_one_probe_per_question():
    """Otherwise a genuinely weak area becomes an interrogation with no exit."""
    plan = _plan()
    score = _score(0.0)
    assert (
        decide_next(score, plan=plan, questions_asked=1, probes_used=0, answers_given=1)
        is Move.PROBE
    )
    assert (
        decide_next(score, plan=plan, questions_asked=1, probes_used=1, answers_given=2)
        is Move.NEXT
    )


# ------------------------------------------------------------------ termination


def test_the_session_ends_once_the_planned_questions_are_done():
    plan = _plan()
    move = decide_next(
        _score(5.0),
        plan=plan,
        questions_asked=plan.questions,
        probes_used=0,
        answers_given=plan.questions,
    )
    assert move is Move.WRAP_UP


def test_a_weak_final_answer_still_ends_the_session():
    """A mock interview that will not let you leave is a bad mock interview."""
    plan = _plan()
    move = decide_next(
        _score(0.0),
        plan=plan,
        questions_asked=plan.questions,
        probes_used=0,
        answers_given=plan.questions,
    )
    assert move is Move.WRAP_UP


def test_the_hard_cap_wins_over_everything():
    plan = Plan(
        profile=Profile.DEVOPS,
        persona=get_persona("principal"),
        difficulty=Difficulty.HARD,
        questions=1000,
        max_probes=1000,
    )
    move = decide_next(
        _score(0.0),
        plan=plan,
        questions_asked=1,
        probes_used=0,
        answers_given=HARD_ANSWER_CAP,
    )
    assert move is Move.WRAP_UP


def test_a_session_always_terminates():
    """Drive the machine with the worst possible answers and prove it stops.

    The three caps are individually tested above; this asserts they compose,
    which is the property that actually matters.
    """
    plan = _plan("principal", Difficulty.HARD)
    questions_asked = 1
    probes_used = 0
    answers_given = 0

    for _ in range(HARD_ANSWER_CAP + 10):
        answers_given += 1
        move = decide_next(
            _score(0.0),
            plan=plan,
            questions_asked=questions_asked,
            probes_used=probes_used,
            answers_given=answers_given,
        )
        if move is Move.WRAP_UP:
            break
        if move is Move.PROBE:
            probes_used += 1
        else:
            questions_asked += 1
            probes_used = 0
    else:
        pytest.fail("the interview never reached wrap_up")

    assert answers_given <= HARD_ANSWER_CAP
    assert questions_asked <= plan.questions


# ------------------------------------------------------------------ personas


@pytest.mark.parametrize(
    ("persona", "difficulty"),
    [
        (persona, difficulty)
        for persona in ("recruiter", "tech_lead", "principal")
        for difficulty in Difficulty
    ],
)
def test_no_persona_can_demand_a_perfect_answer(persona, difficulty):
    """A threshold at or above the maximum probes forever."""
    threshold = probe_threshold(get_persona(persona), difficulty)
    assert 0.0 <= threshold < MAX_SCORE


def test_a_harder_interviewer_is_harder_to_satisfy():
    standard = Difficulty.STANDARD
    assert (
        probe_threshold(get_persona("recruiter"), standard)
        < probe_threshold(get_persona("tech_lead"), standard)
        < probe_threshold(get_persona("principal"), standard)
    )


def test_difficulty_shifts_the_same_interviewer():
    lead = get_persona("tech_lead")
    assert (
        probe_threshold(lead, Difficulty.WARMUP)
        < probe_threshold(lead, Difficulty.STANDARD)
        < probe_threshold(lead, Difficulty.HARD)
    )


def test_an_unknown_persona_falls_back_rather_than_raising():
    assert get_persona("interrogator").key == "tech_lead"


# ------------------------------------------------------------------ probe text


def test_the_models_probe_is_used_when_it_gave_one():
    score = _score(5.0, impact=0.0)
    score.probe = "What changed for the on-call rota afterwards?"
    assert probe_question(score, plan=_plan()) == "What changed for the on-call rota afterwards?"


def test_an_empty_probe_falls_back_to_the_weakest_dimension():
    """A probe decision that produced no question would strand the page."""
    score = _score(5.0, ownership=0.0)
    question = probe_question(score, plan=_plan())
    assert question
    assert "personally" in question


def test_the_plan_defaults_to_five_questions():
    assert _plan().questions == DEFAULT_QUESTIONS
