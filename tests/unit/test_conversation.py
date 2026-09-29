"""The history window and query contextualisation.

Both are pure functions with a cost consequence: get the window wrong and every
turn of every session pays for it, get contextualisation wrong and follow-up
questions retrieve the wrong thing.
"""

from __future__ import annotations

from career_copilot.core.conversation import (
    MAX_HISTORY_TURNS,
    Turn,
    as_messages,
    contextualise,
    window,
)


def _conversation(pairs: int) -> list[Turn]:
    turns: list[Turn] = []
    for index in range(pairs):
        turns.append(Turn(role="user", content=f"question {index}"))
        turns.append(Turn(role="assistant", content=f"answer {index}"))
    return turns


# ------------------------------------------------------------------ window


def test_no_history_is_an_empty_window():
    assert window(None) == []
    assert window([]) == []


def test_a_short_conversation_survives_intact():
    turns = _conversation(2)
    assert [t.content for t in window(turns)] == [t.content for t in turns]


def test_chronological_order_is_preserved():
    kept = window(_conversation(3))
    assert kept[0].content == "question 0"
    assert kept[-1].content == "answer 2"


def test_the_turn_budget_keeps_the_most_recent():
    kept = window(_conversation(10))
    assert len(kept) == MAX_HISTORY_TURNS
    assert kept[-1].content == "answer 9"


def test_the_character_budget_stops_the_walk():
    """Cost grows with every re-sent turn, so the budget is a real limit."""
    turns = [Turn(role="user", content="x" * 3000), Turn(role="assistant", content="y" * 3000)]
    kept = window(turns, max_chars=4000)
    assert len(kept) == 1
    assert kept[0].content.startswith("y")


def test_a_turn_is_never_truncated():
    """Half an answer is worse context than no answer."""
    turns = [Turn(role="assistant", content="z" * 5000)]
    assert window(turns, max_chars=1000) == []


def test_empty_turns_are_skipped():
    turns = [Turn(role="user", content="  "), Turn(role="assistant", content="real")]
    assert [t.content for t in window(turns)] == ["real"]


def test_content_is_stripped():
    assert window([Turn(role="user", content="  spaced  ")])[0].content == "spaced"


# ------------------------------------------------------------------ messages


def test_messages_are_in_the_wire_format():
    messages = as_messages(_conversation(1))
    assert messages == [
        {"role": "user", "content": "question 0"},
        {"role": "assistant", "content": "answer 0"},
    ]


# ------------------------------------------------------------------ contextualise


def test_a_first_question_is_unchanged():
    assert contextualise("what is TARA?", None) == "what is TARA?"
    assert contextualise("what is TARA?", []) == "what is TARA?"


def test_a_follow_up_carries_the_previous_question():
    """ "and where?" alone retrieves nothing and reads as out-of-domain."""
    turns = [
        Turn(role="user", content="what Kubernetes experience do I have?"),
        Turn(role="assistant", content="You ran clusters at Bosch."),
    ]
    assert contextualise("and where?", turns) == (
        "what Kubernetes experience do I have?\nand where?"
    )


def test_only_the_most_recent_question_is_carried():
    """One turn fixes the common case; more drags a whole conversation into
    the search text and hurts when the subject changes."""
    turns = [
        Turn(role="user", content="first topic"),
        Turn(role="assistant", content="answer"),
        Turn(role="user", content="second topic"),
        Turn(role="assistant", content="answer"),
    ]
    contextualised = contextualise("follow up", turns)
    assert "second topic" in contextualised
    assert "first topic" not in contextualised


def test_assistant_turns_are_never_carried_into_the_search():
    """The model's own words are not a search query."""
    turns = [Turn(role="assistant", content="I found three roles at Bosch.")]
    assert contextualise("which ones?", turns) == "which ones?"
