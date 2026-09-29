"""Rubric parsing and the properties everything downstream relies on.

The model's reply is untrusted in the ordinary way - it can omit a field, return
a string where a number belongs, or overshoot the scale. None of that may reach
the database, because a score out of range silently corrupts every average the
Progress page will compute from it.
"""

from __future__ import annotations

import json

import pytest

from career_copilot.core.errors import ToolError
from career_copilot.core.types import Profile
from career_copilot.interview import rubric as rubric_module
from career_copilot.interview.rubric import (
    DIMENSIONS,
    MAX_SCORE,
    RubricScore,
    dimension_keys,
    score_answer,
)
from tests.helpers import make_chat_result

_FULL = {
    "structure": 4,
    "specificity": 2,
    "ownership": 3,
    "impact": 1,
    "relevance": 5,
    "feedback": "Clear story, no numbers.",
    "improved_answer": "Rewritten.",
    "probe": "What was the actual latency?",
}


def _reply(payload: dict, *, wrapper: str = "{body}") -> str:
    return wrapper.format(body=json.dumps(payload))


def _patch_chat(monkeypatch, raw: str) -> None:
    monkeypatch.setattr(rubric_module, "chat", lambda messages, **_: make_chat_result(raw))


# ------------------------------------------------------------------ parsing


def test_a_clean_reply_parses(monkeypatch):
    _patch_chat(monkeypatch, _reply(_FULL))
    score = score_answer("q", "a", profile=Profile.DEVOPS)
    assert score.specificity == 2.0
    assert score.probe == "What was the actual latency?"


def test_json_wrapped_in_prose_and_fences_still_parses(monkeypatch):
    """Models do this constantly. Failing on it would be a self-inflicted bug."""
    _patch_chat(
        monkeypatch,
        _reply(_FULL, wrapper="Here you go:\n```json\n{body}\n```\nHope that helps!"),
    )
    assert score_answer("q", "a", profile=Profile.DEVOPS).structure == 4.0


def test_a_reply_with_no_json_is_a_typed_error(monkeypatch):
    _patch_chat(monkeypatch, "I would rather not.")
    with pytest.raises(ToolError):
        score_answer("q", "a", profile=Profile.DEVOPS)


# ------------------------------------------------------------------ clamping


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        (9.0, MAX_SCORE),  # over the top of the scale
        (-3.0, 0.0),  # under the bottom
        ("excellent", 0.0),  # a word where a number belongs
        (None, 0.0),  # omitted entirely
        (True, 0.0),  # bool is an int in Python; it is not a score
    ],
)
def test_out_of_range_scores_are_clamped(monkeypatch, given, expected):
    payload = {**_FULL, "impact": given}
    _patch_chat(monkeypatch, _reply(payload))
    assert score_answer("q", "a", profile=Profile.DEVOPS).impact == expected


def test_a_missing_dimension_scores_zero_not_a_midpoint(monkeypatch):
    """Zero rather than 2.5, so an un-scored dimension looks wrong on the chart -
    because it is."""
    payload = {key: value for key, value in _FULL.items() if key != "ownership"}
    _patch_chat(monkeypatch, _reply(payload))
    assert score_answer("q", "a", profile=Profile.DEVOPS).ownership == 0.0


# ------------------------------------------------------------------ properties


def test_overall_is_the_mean_of_the_five():
    score = RubricScore(structure=1, specificity=2, ownership=3, impact=4, relevance=5)
    assert score.overall == 3.0


def test_weakest_finds_the_lowest():
    score = RubricScore(structure=4, specificity=0.5, ownership=3, impact=4, relevance=5)
    assert score.weakest == ("specificity", 0.5)


def test_ties_break_towards_structure():
    """Deliberate: if two dimensions are equally weak, the one worth fixing
    first is the one the others are built on."""
    score = RubricScore(structure=1, specificity=1, ownership=1, impact=1, relevance=1)
    assert score.weakest[0] == "structure"


def test_the_scores_mapping_covers_every_declared_dimension():
    """Guards the seam between the rubric and the database columns: adding a
    dimension without a column, or vice versa, breaks here first."""
    score = RubricScore(structure=1, specificity=1, ownership=1, impact=1, relevance=1)
    assert tuple(score.scores) == dimension_keys()
    assert len(DIMENSIONS) == 5


def test_render_shows_the_scale_not_a_bare_number():
    """0-5 and 0-1 both live in this app; an unlabelled 3.0 is ambiguous."""
    rendered = RubricScore(structure=3, specificity=3, ownership=3, impact=3, relevance=3).render()
    assert "3.0 / 5" in rendered


def test_a_score_outside_the_range_cannot_be_constructed():
    """The clamp is the first defence; the model is the second."""
    with pytest.raises(ValueError, match="less than or equal to 5"):
        RubricScore(structure=7, specificity=1, ownership=1, impact=1, relevance=1)


# ------------------------------------------------------------------ worked example


def test_an_echoed_answer_is_discarded(monkeypatch):
    """Showing a candidate their own words back under "how this should be built"
    reads as approval. Better to show nothing."""
    answer = "I worked on cybersecurity for a while and we improved things a lot."
    _patch_chat(monkeypatch, _reply({**_FULL, "improved_answer": answer}))
    assert score_answer("q", answer, profile=Profile.DEVOPS).improved_answer == ""


def test_an_echo_is_caught_through_whitespace_and_case(monkeypatch):
    answer = "We fixed it."
    _patch_chat(monkeypatch, _reply({**_FULL, "improved_answer": "  we   FIXED it.  "}))
    assert score_answer("q", answer, profile=Profile.DEVOPS).improved_answer == ""


def test_a_one_word_improvement_is_discarded(monkeypatch):
    """A worked example has to be long enough to be an example."""
    _patch_chat(monkeypatch, _reply({**_FULL, "improved_answer": "Be specific."}))
    assert score_answer("q", "an answer", profile=Profile.DEVOPS).improved_answer == ""


def test_a_real_worked_example_survives(monkeypatch):
    example = (
        "At [the company], I was asked to [the task]. I used CANoe to [what you did with it], "
        "which reduced [the metric] by [how much]."
    )
    _patch_chat(monkeypatch, _reply({**_FULL, "improved_answer": example}))
    assert score_answer("q", "i used CANoe", profile=Profile.DEVOPS).improved_answer == example


def test_the_prompt_forbids_returning_the_answer_unchanged():
    """The guard above is the second line of defence; this is the first."""
    assert "NEVER return their answer unchanged" in rubric_module.SYSTEM_PROMPT
    assert "bracketed gap" in rubric_module.SYSTEM_PROMPT


def test_the_prompt_requires_naming_an_injection_attempt():
    prompt = rubric_module.SYSTEM_PROMPT
    assert "FIRST sentence of `feedback`" in prompt
    assert "instruction instead of an answer" in prompt
