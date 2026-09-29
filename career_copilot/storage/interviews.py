"""Repository for interview sessions and answers.

The aggregation functions at the bottom are the reason this data is in SQL at
all. "Average specificity across every DevOps session in the last 30 days" is
one GROUP BY here and a loop over every row in Python anywhere else, and the
Progress dashboard is nothing but questions of that shape.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from career_copilot.core.logging import get_logger
from career_copilot.core.types import Profile
from career_copilot.interview.rubric import RubricScore, dimension_keys
from career_copilot.storage.db import StorageError, session_scope
from career_copilot.storage.models import InterviewAnswer, InterviewSession

__all__ = [
    "SessionScore",
    "answer_count",
    "capture_comparison",
    "dimension_averages",
    "finish_session",
    "get_session",
    "latest_unfinished",
    "list_sessions",
    "questions_asked",
    "record_answer",
    "session_scores",
    "start_session",
    "totals",
    "weakest_dimensions",
]

log = get_logger(__name__)


def _new_id() -> str:
    return uuid.uuid4().hex[:16]


def start_session(
    *,
    profile: Profile,
    persona: str,
    difficulty: str,
    planned_questions: int = 5,
    job_id: str | None = None,
) -> InterviewSession:
    """Open a session. The row exists before the first question is asked.

    Deliberately: a session abandoned after two answers is still data about how
    you perform, and writing the parent row only on completion would throw that
    away exactly when it is most informative.
    """
    with session_scope() as session:
        record = InterviewSession(
            id=_new_id(),
            profile=str(profile),
            persona=persona,
            difficulty=difficulty,
            planned_questions=planned_questions,
            job_id=job_id,
        )
        session.add(record)
        session.flush()
        session.expunge(record)
        log.info(
            "interview started",
            extra={"session": record.id, "profile": str(profile), "persona": persona},
        )
        return record


def record_answer(
    session_id: str,
    *,
    question: str,
    answer: str,
    score: RubricScore,
    is_probe: bool = False,
    captured_as: str = "typed",
    duration_seconds: float | None = None,
) -> InterviewAnswer:
    """Store one graded answer. Position is assigned here, not by the caller.

    The caller is a Streamlit page that re-runs on every click; letting it own a
    counter is how you get two answers at position 3.
    """
    with session_scope() as session:
        if session.get(InterviewSession, session_id) is None:
            raise StorageError(f"no interview session with id {session_id!r}")

        next_position = (
            session.scalar(
                select(func.count())
                .select_from(InterviewAnswer)
                .where(InterviewAnswer.session_id == session_id)
            )
            or 0
        ) + 1

        record = InterviewAnswer(
            session_id=session_id,
            position=next_position,
            question=question,
            answer=answer,
            is_probe=is_probe,
            captured_as=captured_as,
            word_count=len(answer.split()),
            duration_seconds=duration_seconds,
            structure=score.structure,
            specificity=score.specificity,
            ownership=score.ownership,
            impact=score.impact,
            relevance=score.relevance,
            feedback=score.feedback or None,
            improved_answer=score.improved_answer or None,
        )
        session.add(record)
        session.flush()
        session.expunge(record)
        log.info(
            "answer recorded",
            extra={"session": session_id, "position": next_position, "probe": is_probe},
        )
        return record


def finish_session(session_id: str, summary: str) -> None:
    with session_scope() as session:
        record = session.get(InterviewSession, session_id)
        if record is None:
            raise StorageError(f"no interview session with id {session_id!r}")
        record.ended_at = datetime.now(UTC)
        record.summary = summary
        log.info("interview finished", extra={"session": session_id})


def get_session(session_id: str) -> InterviewSession | None:
    """Eager-loads the answers - the row is detached before it leaves here."""
    with session_scope() as session:
        record = session.scalar(
            select(InterviewSession)
            .options(selectinload(InterviewSession.answers))
            .where(InterviewSession.id == session_id)
        )
        if record is not None:
            session.expunge(record)
        return record


def list_sessions(
    *,
    profile: Profile | None = None,
    completed_only: bool = False,
    limit: int = 20,
) -> list[InterviewSession]:
    with session_scope() as session:
        statement = (
            select(InterviewSession)
            .options(selectinload(InterviewSession.answers))
            .order_by(InterviewSession.started_at.desc())
            .limit(limit)
        )
        if profile:
            statement = statement.where(InterviewSession.profile == str(profile))
        if completed_only:
            statement = statement.where(InterviewSession.ended_at.is_not(None))
        records = list(session.scalars(statement))
        for record in records:
            session.expunge(record)
        return records


def latest_unfinished(*, min_answers: int = 1) -> InterviewSession | None:
    """The most recent session that was started and never closed.

    This is what makes a browser refresh survivable. The answers were always in
    the database; without this they were merely *stored*, not reachable, which
    is not the same thing as not being lost but feels identical to the person
    who just lost their transcript.
    """
    with session_scope() as session:
        record = session.scalar(
            select(InterviewSession)
            .options(selectinload(InterviewSession.answers))
            .where(InterviewSession.ended_at.is_(None))
            .order_by(InterviewSession.started_at.desc())
        )
        if record is None or len(record.answers) < min_answers:
            return None
        session.expunge(record)
        return record


def questions_asked(session_id: str) -> list[str]:
    """Fresh questions only, in order. Probes are follow-ups, not new ground, and
    feeding them back as 'already asked' would suppress the topic they belong to."""
    with session_scope() as session:
        return list(
            session.scalars(
                select(InterviewAnswer.question)
                .where(
                    InterviewAnswer.session_id == session_id,
                    InterviewAnswer.is_probe.is_(False),
                )
                .order_by(InterviewAnswer.position)
            )
        )


def answer_count(session_id: str, *, probes: bool | None = None) -> int:
    """How many answers this session holds. `probes` filters to one kind."""
    with session_scope() as session:
        statement = (
            select(func.count())
            .select_from(InterviewAnswer)
            .where(InterviewAnswer.session_id == session_id)
        )
        if probes is not None:
            statement = statement.where(InterviewAnswer.is_probe.is_(probes))
        return int(session.scalar(statement) or 0)


def dimension_averages(
    *,
    profile: Profile | None = None,
    since_days: int | None = None,
    session_id: str | None = None,
) -> dict[str, float]:
    """Mean score per dimension, in DIMENSIONS order.

    Returns every dimension even when there is no data, with 0.0 for the empty
    case, so a chart never has to cope with a missing series. Callers that need
    to distinguish "scored zero" from "never answered" should check
    `answer_count` - which is why that function exists separately.
    """
    keys = dimension_keys()
    columns = [func.avg(getattr(InterviewAnswer, key)) for key in keys]

    with session_scope() as session:
        statement = select(*columns).select_from(InterviewAnswer)

        if session_id:
            statement = statement.where(InterviewAnswer.session_id == session_id)
        if profile or since_days is not None:
            statement = statement.join(
                InterviewSession, InterviewAnswer.session_id == InterviewSession.id
            )
        if profile:
            statement = statement.where(InterviewSession.profile == str(profile))
        if since_days is not None:
            cutoff = datetime.now(UTC) - timedelta(days=since_days)
            statement = statement.where(InterviewSession.started_at >= cutoff)

        row: Sequence[float | None] = session.execute(statement).one()
        return {key: round(float(value or 0.0), 2) for key, value in zip(keys, row, strict=True)}


def weakest_dimensions(
    *,
    profile: Profile | None = None,
    since_days: int | None = None,
    limit: int = 2,
) -> list[tuple[str, float]]:
    """The dimensions to practise, worst first. Seeds "practise my weak areas"."""
    averages = dimension_averages(profile=profile, since_days=since_days)
    return sorted(averages.items(), key=lambda item: item[1])[:limit]


# ---------------------------------------------------------------- cross-session

# Everything below answers a question the Progress page asks. They are separate
# functions rather than one "give me the dashboard data" call because each one is
# a different GROUP BY, and a single blob would recompute all of them whenever
# any one filter changed.


@dataclass(frozen=True)
class SessionScore:
    """One session reduced to its five averages - a point on the trend chart."""

    session_id: str
    started_at: datetime
    profile: str
    persona: str
    answers: int
    scores: dict[str, float]

    @property
    def overall(self) -> float:
        values = self.scores.values()
        return round(sum(values) / len(values), 2) if values else 0.0


def session_scores(
    *,
    profile: Profile | None = None,
    since_days: int | None = None,
    limit: int = 30,
) -> list[SessionScore]:
    """Per-session averages, oldest first - the shape a trend chart wants.

    Ordered oldest-first deliberately: the query takes the most recent `limit`
    sessions, then hands them back in reading order, so a chart plots left to
    right without the caller having to know to reverse it.
    """
    keys = dimension_keys()
    columns = [func.avg(getattr(InterviewAnswer, key)).label(key) for key in keys]

    with session_scope() as session:
        statement = (
            select(
                InterviewSession.id,
                InterviewSession.started_at,
                InterviewSession.profile,
                InterviewSession.persona,
                func.count(InterviewAnswer.id).label("answers"),
                *columns,
            )
            .join(InterviewAnswer, InterviewAnswer.session_id == InterviewSession.id)
            .group_by(InterviewSession.id)
            .order_by(InterviewSession.started_at.desc())
            .limit(limit)
        )
        if profile:
            statement = statement.where(InterviewSession.profile == str(profile))
        if since_days is not None:
            cutoff = datetime.now(UTC) - timedelta(days=since_days)
            statement = statement.where(InterviewSession.started_at >= cutoff)

        rows = session.execute(statement).all()

    scores = [
        SessionScore(
            session_id=str(row[0]),
            started_at=row[1],
            profile=str(row[2]),
            persona=str(row[3]),
            answers=int(row[4]),
            scores={
                key: round(float(value or 0.0), 2) for key, value in zip(keys, row[5:], strict=True)
            },
        )
        for row in rows
    ]
    scores.reverse()
    return scores


def capture_comparison(*, profile: Profile | None = None) -> dict[str, dict[str, float]]:
    """Spoken answers versus written ones.

    Worth measuring rather than assuming. Most people are visibly worse out loud
    than on paper, and the gap is the thing interview practice is for - but it is
    only visible because `captured_as` was recorded at the time.

    Returns {"voice": {...}, "typed": {...}} with an `answers` count alongside the
    dimension means, and omits a mode entirely when nothing was captured that way.
    """
    keys = dimension_keys()
    columns = [func.avg(getattr(InterviewAnswer, key)) for key in keys]

    with session_scope() as session:
        statement = select(
            InterviewAnswer.captured_as,
            func.count(InterviewAnswer.id),
            func.avg(InterviewAnswer.word_count),
            *columns,
        ).group_by(InterviewAnswer.captured_as)

        if profile:
            statement = statement.join(
                InterviewSession, InterviewAnswer.session_id == InterviewSession.id
            ).where(InterviewSession.profile == str(profile))

        rows = session.execute(statement).all()

    result: dict[str, dict[str, float]] = {}
    for row in rows:
        means = {
            key: round(float(value or 0.0), 2) for key, value in zip(keys, row[3:], strict=True)
        }
        means["answers"] = float(row[1])
        means["words"] = round(float(row[2] or 0.0), 1)
        result[str(row[0])] = means
    return result


def totals(*, profile: Profile | None = None) -> dict[str, int]:
    """Headline counts for the stat tiles."""
    with session_scope() as session:
        sessions = select(func.count()).select_from(InterviewSession)
        answers = select(func.count()).select_from(InterviewAnswer)
        probes = answers.where(InterviewAnswer.is_probe.is_(True))

        if profile:
            sessions = sessions.where(InterviewSession.profile == str(profile))
            joined = InterviewAnswer.session_id == InterviewSession.id
            answers = answers.join(InterviewSession, joined).where(
                InterviewSession.profile == str(profile)
            )
            probes = probes.join(InterviewSession, joined).where(
                InterviewSession.profile == str(profile)
            )

        return {
            "sessions": int(session.scalar(sessions) or 0),
            "answers": int(session.scalar(answers) or 0),
            "probes": int(session.scalar(probes) or 0),
        }
