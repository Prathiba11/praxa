"""Interview tools.

Two, both read-only. The agent in interview mode can generate a question and
grade an answer; it cannot write a document, touch the funnel, or persist a
session. Persistence belongs to the Interview page, which owns the session and
knows the answer's position in it - an agent that could write answer rows would
be a second, unsynchronised writer to the same session.

The page does not need these tools; it calls the interview package directly.
They exist so the agent can conduct an interview conversationally, and so the
capability is available from chat without leaving the mode's blast radius.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from career_copilot.core.logging import get_logger
from career_copilot.core.types import Profile
from career_copilot.interview.personas import DEFAULT_PERSONA, Difficulty, get_persona
from career_copilot.interview.questions import next_question
from career_copilot.interview.rubric import score_answer
from career_copilot.tools._shared import resolve_job
from career_copilot.tools.base import Tool

__all__ = [
    "GetInterviewQuestionArgs",
    "ScoreStarAnswerArgs",
    "get_interview_question",
    "score_star_answer",
]

log = get_logger(__name__)


class GetInterviewQuestionArgs(BaseModel):
    profile: Profile = Field(
        description="Which of the candidate's three profiles to interview for."
    )
    difficulty: Difficulty = Field(
        default=Difficulty.STANDARD,
        description="warmup for an opener, standard for a normal question, hard for a challenge.",
    )
    persona: str = Field(
        default=DEFAULT_PERSONA,
        description="recruiter, tech_lead or principal. Unknown values fall back to tech_lead.",
    )
    job_id: str | None = Field(
        default=None,
        description="Id of a stored job to interview against, from search_jobs.",
    )
    already_asked: list[str] = Field(
        default_factory=list,
        description="Questions already asked this session, so the next one is new ground.",
    )


def _run_question(args: GetInterviewQuestionArgs) -> str:
    job_text: str | None = None
    job_label: str | None = None
    if args.job_id:
        job = resolve_job(args.job_id, None)
        job_text, job_label = job.text, job.label

    question = next_question(
        args.profile,
        persona=get_persona(args.persona),
        difficulty=args.difficulty,
        job_text=job_text,
        job_label=job_label,
        asked=args.already_asked,
    )
    return f"{question.text}\n\n(grounded in {question.grounding})"


class ScoreStarAnswerArgs(BaseModel):
    question: str = Field(max_length=2000, description="The question that was asked.")
    answer: str = Field(max_length=20000, description="What the candidate said, verbatim.")
    profile: Profile = Field(description="Which profile the candidate is interviewing for.")
    persona: str = Field(
        default=DEFAULT_PERSONA,
        description="Who is assessing: recruiter, tech_lead or principal.",
    )


def _run_score(args: ScoreStarAnswerArgs) -> str:
    score = score_answer(
        args.question,
        args.answer,
        profile=args.profile,
        persona_style=get_persona(args.persona).style,
    )
    return score.render()


get_interview_question = Tool(
    name="get_interview_question",
    description="""
        Produce the next interview question for one of the candidate's profiles,
        grounded in their knowledge base or in a stored job posting. Pass
        already_asked so the interview does not circle. Returns the question and
        where it came from.
    """,
    args_model=GetInterviewQuestionArgs,
    handler=_run_question,
)

score_star_answer = Tool(
    name="score_star_answer",
    description="""
        Grade one interview answer against the STAR rubric: structure,
        specificity, ownership, impact and relevance, each 0-5. Returns the
        scores, written feedback, a stronger version of their own answer that
        invents no new facts, and the follow-up question to ask next.
    """,
    args_model=ScoreStarAnswerArgs,
    handler=_run_score,
)
