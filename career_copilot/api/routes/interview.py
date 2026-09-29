"""Interview practice, as a session rather than a conversation.

Practice already worked in chat - ask for a question in interview mode and one
arrives. What chat cannot do is hold a session. Each message there is
independent, so nothing knows that a question is outstanding and that the next
thing typed is the answer to it. The observed result was a candidate asking for
a question twice and getting two questions, then saying "I don't know" and being
handed a lecture on the STAR framework instead of the interview moving on. The
mode prompt says "ask one question, wait for the answer, then critique it",
which without state behind it is a hope rather than a flow.

None of the machinery is new. `interview.session` already scores an answer,
stores it, decides whether to probe or move on, and rebuilds a session from the
database after a refresh - it was written for the Streamlit page and is reused
here unchanged. This router is the thin part: it turns those functions into
endpoints and translates their dataclasses into the wire shapes.

**Why scoring and asking are two calls.** `submit_answer` scores and stores;
`POST .../next` generates the following question. Doing both in one request
meant several seconds of nothing before anything appeared. Split, the score - the
part the candidate is waiting for - arrives first, and the next question loads
behind it. Same total time, better to sit through.

**The session lives in the database, not in the page.** A refresh, a closed tab
or a second window all land on the same rows. The one thing not recovered is a
question that was on screen unanswered, because only answered questions are
stored; the page asks for a new one instead. Nothing the candidate produced is
lost.
"""

from __future__ import annotations

from typing import Any, cast, get_args

from fastapi import APIRouter, HTTPException

from career_copilot.api.schemas import (
    AnswerOut,
    AnswerRequest,
    DifficultyValue,
    InterviewOptions,
    InterviewSessionOut,
    MoveValue,
    PersonaOut,
    ProfileValue,
    QuestionOut,
    ScoreOut,
    StartInterviewRequest,
    TurnOut,
)
from career_copilot.core.errors import CopilotError
from career_copilot.core.logging import get_logger
from career_copilot.core.session import use_session
from career_copilot.core.types import Profile
from career_copilot.core.usage import new_session_id
from career_copilot.interview.engine import DEFAULT_QUESTIONS, Move, Plan
from career_copilot.interview.personas import (
    DEFAULT_PERSONA,
    PERSONAS,
    Difficulty,
    Persona,
    get_persona,
)
from career_copilot.interview.questions import Question
from career_copilot.interview.rubric import RubricScore
from career_copilot.interview.session import (
    RestoredSession,
    Turn,
    following_question,
    restore,
    start_session,
    submit_answer,
)
from career_copilot.storage.db import init_db

router = APIRouter(prefix="/interview", tags=["interview"])
log = get_logger(__name__)


# ------------------------------------------------------------------ mapping


def _persona_out(persona: Persona) -> PersonaOut:
    return PersonaOut(key=persona.key, name=persona.name, opening=persona.opening)


def _question_out(question: Question) -> QuestionOut:
    return QuestionOut(text=question.text, grounding=question.grounding, focus=question.focus)


def _score_out(score: RubricScore) -> ScoreOut:
    return ScoreOut(
        structure=score.structure,
        specificity=score.specificity,
        ownership=score.ownership,
        impact=score.impact,
        relevance=score.relevance,
        overall=score.overall,
        feedback=score.feedback,
        improved_answer=score.improved_answer,
    )


def _turn_out(turn: Turn) -> TurnOut:
    return TurnOut(
        question=turn.question,
        answer=turn.answer,
        score=_score_out(turn.score),
        is_probe=turn.is_probe,
    )


def _session_out(
    session_id: str,
    plan: Plan,
    *,
    job_id: str | None = None,
    turns: list[Turn] | None = None,
    question: Question | None = None,
) -> InterviewSessionOut:
    return InterviewSessionOut(
        session_id=session_id,
        profile=_profile_value(str(plan.profile)),
        persona=_persona_out(plan.persona),
        difficulty=_difficulty_value(str(plan.difficulty)),
        planned_questions=plan.questions,
        job_id=job_id,
        turns=[_turn_out(turn) for turn in (turns or [])],
        question=_question_out(question) if question else None,
    )


def _narrowed(value: str, literal: Any, what: str) -> Any:
    """Narrow a stored string to one of a Literal's members, or refuse it.

    `get_args` reads the permitted values off the type itself, so the check and
    the annotation cannot drift apart - which is the whole reason this exists
    rather than a `# type: ignore` on a bare return. A row written by an older
    version, or by hand, fails here at the boundary rather than reaching a
    client that has no branch for it.
    """
    allowed = get_args(literal)
    if value not in allowed:
        raise HTTPException(
            status_code=500, detail=f"stored {what} {value!r} is not one of {sorted(allowed)}"
        )
    return value


def _profile_value(value: str) -> ProfileValue:
    return cast(ProfileValue, _narrowed(value, ProfileValue, "profile"))


def _difficulty_value(value: str) -> DifficultyValue:
    return cast(DifficultyValue, _narrowed(value, DifficultyValue, "difficulty"))


# ------------------------------------------------------------------- routes


@router.get("/options", response_model=InterviewOptions)
def options() -> InterviewOptions:
    """The personas and difficulties, so the start form hard-codes nothing.

    A page with its own copy of this list is a page that silently disagrees with
    the server the day a persona is added.
    """
    return InterviewOptions(
        personas=[_persona_out(persona) for persona in PERSONAS.values()],
        difficulties=["warmup", "standard", "hard"],
        default_persona=DEFAULT_PERSONA,
        default_questions=DEFAULT_QUESTIONS,
    )


@router.post("/sessions", response_model=InterviewSessionOut, status_code=201)
def start(payload: StartInterviewRequest) -> InterviewSessionOut:
    """Open a session and return its opening question."""
    init_db()
    plan = Plan(
        profile=Profile(payload.profile),
        persona=get_persona(payload.persona),
        difficulty=Difficulty(payload.difficulty),
        questions=payload.questions,
    )

    with use_session(new_session_id()):
        try:
            session_id = start_session(plan, job_id=payload.job_id)
            question = following_question(session_id, plan=plan)
        except CopilotError as exc:
            raise HTTPException(status_code=502, detail=exc.user_message) from exc

    log.info(
        "interview started",
        extra={
            "session": session_id,
            "profile": str(plan.profile),
            "persona": plan.persona.key,
            "difficulty": str(plan.difficulty),
        },
    )
    return _session_out(session_id, plan, job_id=payload.job_id, question=question)


@router.get("/sessions/{session_id}", response_model=InterviewSessionOut)
def get_session(session_id: str) -> InterviewSessionOut:
    """Rebuild a session from the stored rows, for a refresh or a second tab."""
    init_db()
    found: RestoredSession | None = restore(session_id)
    if found is None:
        raise HTTPException(status_code=404, detail="No such interview session.")
    return _session_out(found.session_id, found.plan, job_id=found.job_id, turns=found.turns)


@router.post("/sessions/{session_id}/answers", response_model=AnswerOut)
def answer(session_id: str, payload: AnswerRequest) -> AnswerOut:
    """Score one answer, store it, and say what happens next.

    The answer is persisted before anything else, so an interrupted turn never
    loses the one part of the session the candidate actually produced.
    """
    init_db()
    found = restore(session_id)
    if found is None:
        raise HTTPException(status_code=404, detail="No such interview session.")

    with use_session(new_session_id()):
        try:
            result = submit_answer(
                session_id,
                plan=found.plan,
                question=payload.question,
                answer=payload.answer,
                is_probe=payload.is_probe,
                captured_as=payload.captured_as,
                duration_seconds=payload.duration_seconds,
            )
        except CopilotError as exc:
            raise HTTPException(status_code=502, detail=exc.user_message) from exc

    return AnswerOut(
        score=_score_out(result.score),
        move=_move_value(result.move),
        probe=_question_out(result.probe) if result.probe else None,
        summary=result.summary,
    )


@router.post("/sessions/{session_id}/next", response_model=QuestionOut)
def next_question_route(session_id: str) -> QuestionOut:
    """The following fresh question, avoiding everything already asked."""
    init_db()
    found = restore(session_id)
    if found is None:
        raise HTTPException(status_code=404, detail="No such interview session.")

    with use_session(new_session_id()):
        try:
            question = following_question(session_id, plan=found.plan)
        except CopilotError as exc:
            raise HTTPException(status_code=502, detail=exc.user_message) from exc
    return _question_out(question)


def _move_value(move: Move) -> MoveValue:
    """`Move` is a StrEnum; the client is promised the three literals."""
    return cast(MoveValue, _narrowed(str(move), MoveValue, "move"))
