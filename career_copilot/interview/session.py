"""One turn of an interview, start to finish.

Streamlit re-runs the whole script on every interaction, so a session cannot
live in local variables - it lives in the database, and each turn reads what it
needs back out. That is why the counts driving `decide_next` are queried rather
than incremented: a page that owns a counter loses it the moment the user
refreshes, and gets it wrong the moment they double-click.

Two things here are shaped by how long a model call takes.

**Scoring and asking are separate calls, so they are separate steps.** Doing both
inside one submit meant five seconds of nothing before anything appeared. Now
`submit_answer` scores and stores, and the page renders that; generating the
next question is a second step it takes afterwards, with its own spinner. Same
total time, but the part the user is waiting for arrives first.

**A follow-up costs nothing.** The probe is already in the rubric result, so a
weak answer produces its follow-up with no further call at all.

`restore` is the other half of "the session lives in the database": it rebuilds
a page's worth of state from the stored rows after a refresh.

This module is deliberately not re-exported from ``interview/__init__``: it
imports the storage layer, which imports the rubric, and a package that imports
its own dependents is a cycle waiting to bite.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from career_copilot.core.logging import get_logger
from career_copilot.core.types import Profile
from career_copilot.interview.engine import (
    Move,
    Plan,
    decide_next,
    probe_question,
    write_summary,
)
from career_copilot.interview.personas import Difficulty, get_persona
from career_copilot.interview.questions import Question, next_question
from career_copilot.interview.rubric import RubricScore, score_answer
from career_copilot.storage import interviews as repo

__all__ = [
    "RestoredSession",
    "Turn",
    "TurnResult",
    "following_question",
    "restore",
    "start_session",
    "submit_answer",
    "transcript_of",
]

log = get_logger(__name__)


@dataclass(frozen=True)
class TurnResult:
    """What one submitted answer produced.

    `probe` is populated only for a follow-up, because that text comes free with
    the score. A fresh question is NOT here - the page asks for it separately so
    it can paint the score first.
    """

    score: RubricScore
    move: Move
    probe: Question | None = None
    summary: str | None = None


@dataclass(frozen=True)
class Turn:
    """One answered question, as the transcript shows it."""

    question: str
    answer: str
    score: RubricScore
    is_probe: bool = False


@dataclass(frozen=True)
class RestoredSession:
    """Enough to put a refreshed page back where it was."""

    session_id: str
    plan: Plan
    turns: list[Turn] = field(default_factory=list)
    job_id: str | None = None


def start_session(plan: Plan, *, job_id: str | None = None) -> str:
    """Open the session row and return its id."""
    session = repo.start_session(
        profile=plan.profile,
        persona=plan.persona.key,
        difficulty=str(plan.difficulty),
        planned_questions=plan.questions,
        job_id=job_id,
    )
    return session.id


def following_question(
    session_id: str,
    *,
    plan: Plan,
    job_text: str | None = None,
    job_label: str | None = None,
    focus_on: Sequence[str] = (),
) -> Question:
    """The next fresh question, avoiding everything already asked.

    Used for the opening question and every subsequent one - and, after a
    refresh, to pick the interview back up. The already-asked list comes from
    the database, so it is correct in all three cases.
    """
    return next_question(
        plan.profile,
        persona=plan.persona,
        difficulty=plan.difficulty,
        job_text=job_text,
        job_label=job_label,
        asked=repo.questions_asked(session_id),
        focus_on=focus_on,
        session_id=session_id,
    )


def transcript_of(session_id: str) -> str:
    """The session as text, for the closing debrief."""
    session = repo.get_session(session_id)
    if session is None:
        return ""
    blocks = []
    for answer in session.answers:
        marker = "FOLLOW-UP" if answer.is_probe else "QUESTION"
        blocks.append(f"{marker}: {answer.question}\nANSWER: {answer.answer}")
    return "\n\n".join(blocks)


def restore(session_id: str) -> RestoredSession | None:
    """Rebuild a page's state from the stored rows.

    The question that was on screen unanswered when the tab closed is not
    recovered - it was never stored, because only answered questions are. The
    page asks for a new one instead, which costs a call and is honest: nothing
    the candidate produced is lost, and the interview continues where it was.
    """
    session = repo.get_session(session_id)
    if session is None:
        return None

    plan = Plan(
        profile=Profile(session.profile),
        persona=get_persona(session.persona),
        difficulty=Difficulty(session.difficulty),
        questions=session.planned_questions,
    )
    turns = [
        Turn(
            question=answer.question,
            answer=answer.answer,
            is_probe=answer.is_probe,
            score=RubricScore(
                structure=answer.structure,
                specificity=answer.specificity,
                ownership=answer.ownership,
                impact=answer.impact,
                relevance=answer.relevance,
                feedback=answer.feedback or "",
                improved_answer=answer.improved_answer or "",
            ),
        )
        for answer in session.answers
    ]
    log.info("interview restored", extra={"session": session_id, "turns": len(turns)})
    return RestoredSession(session_id=session.id, plan=plan, turns=turns, job_id=session.job_id)


def submit_answer(
    session_id: str,
    *,
    plan: Plan,
    question: str,
    answer: str,
    is_probe: bool = False,
    captured_as: str = "typed",
    duration_seconds: float | None = None,
) -> TurnResult:
    """Score one answer, store it, and work out what happens next.

    The order matters: the answer is persisted before anything else. An
    interrupted turn - a closed tab, a failed call - must not lose the one piece
    of the session the candidate actually produced.
    """
    score = score_answer(
        question,
        answer,
        profile=plan.profile,
        persona_style=plan.persona.style,
        session_id=session_id,
    )
    repo.record_answer(
        session_id,
        question=question,
        answer=answer,
        score=score,
        is_probe=is_probe,
        captured_as=captured_as,
        duration_seconds=duration_seconds,
    )

    asked = repo.questions_asked(session_id)
    move = decide_next(
        score,
        plan=plan,
        questions_asked=len(asked),
        # Probes are counted against the current question only. A fresh question
        # resets the allowance, which is what "one follow-up per question" means.
        probes_used=1 if is_probe else 0,
        answers_given=repo.answer_count(session_id),
    )

    if move is Move.PROBE:
        return TurnResult(
            score=score,
            move=move,
            probe=Question(
                text=probe_question(score, plan=plan),
                grounding="your previous answer",
                focus=score.weakest[0],
            ),
        )

    if move is Move.NEXT:
        return TurnResult(score=score, move=move)

    summary = write_summary(
        transcript_of(session_id),
        repo.dimension_averages(session_id=session_id),
        plan=plan,
        session_id=session_id,
    )
    repo.finish_session(session_id, summary)
    log.info("interview complete", extra={"session": session_id, "answers": len(asked)})
    return TurnResult(score=score, move=move, summary=summary)
