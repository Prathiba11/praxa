"""Conversation memory: how much of it, and where it is allowed to matter.

Without this, every question is answered as if it were the first. "What
Kubernetes experience do I have?" works; "and where?" is meaningless. Adding
history is easy; adding it *well* means answering three separate questions.

**How much?** A transcript grows without bound and every turn re-sends it, so
cost grows quadratically over a session. The window keeps recent whole turns
within a character budget and drops the rest. Whole turns, because half an
exchange reads worse than none of it.

**Where does it apply?** Three places, deliberately not the same amount:

- *Generation* gets the whole window. That is what makes the model remember
  your name and resolve "it" and "there".
- *Retrieval and the guardrail* get only the immediately preceding question,
  joined to the current one. This is query contextualisation in its cheapest
  form: it is what stops "and where?" from retrieving nothing and from being
  classified as out-of-domain, without an extra model call. The trade-off is
  real - if you change subject abruptly, one stale question is in the search
  text - and one turn is the smallest amount that fixes the common case.

**What is not remembered?** Nothing is persisted. The window lives in the
Streamlit session and dies with it. A CV-shaped conversation on disk is a
liability nobody asked for.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Literal

from pydantic import BaseModel

from career_copilot.core.llm import ChatMessage

__all__ = [
    "MAX_HISTORY_CHARS",
    "MAX_HISTORY_TURNS",
    "Turn",
    "as_messages",
    "contextualise",
    "window",
]

MAX_HISTORY_TURNS = 8
MAX_HISTORY_CHARS = 4000


class Turn(BaseModel):
    """One thing said, by one side."""

    role: Literal["user", "assistant"]
    content: str


def window(
    turns: Sequence[Turn] | None,
    *,
    max_turns: int = MAX_HISTORY_TURNS,
    max_chars: int = MAX_HISTORY_CHARS,
) -> list[Turn]:
    """The most recent turns that fit both budgets, in chronological order.

    Walks backwards so the newest survive, then restores order. A turn that
    would breach the character budget stops the walk rather than being
    truncated: half an answer is worse context than no answer.
    """
    if not turns:
        return []

    kept: list[Turn] = []
    used = 0
    for turn in reversed(turns):
        text = turn.content.strip()
        if not text:
            continue
        if len(kept) >= max_turns or used + len(text) > max_chars:
            break
        kept.append(Turn(role=turn.role, content=text))
        used += len(text)

    kept.reverse()
    return kept


def as_messages(turns: Iterable[Turn]) -> list[ChatMessage]:
    """Turns in the wire format, ready to sit between system and question."""
    return [{"role": turn.role, "content": turn.content} for turn in turns]


def contextualise(question: str, turns: Sequence[Turn] | None) -> str:
    """The text retrieval and the guardrail should see.

    Only the immediately preceding user turn is carried over. Enough to resolve
    "and where?"; little enough that a change of subject does not drag the whole
    conversation into the search.
    """
    if not turns:
        return question

    previous = next(
        (turn.content.strip() for turn in reversed(turns) if turn.role == "user"),
        "",
    )
    return f"{previous}\n{question}" if previous else question
