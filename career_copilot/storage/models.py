"""SQLAlchemy models.

Job postings are RECORDS, not prose. They have a company, a location, a date and
a status, and the questions asked of them - "what is new today", "which have I
applied to", "how often does Terraform appear" - are counting and filtering
questions. Those belong in SQL, where the answer is exact.

The semantic half (find me roles *like* this one) stays in the vector store. The
two are deliberately separate; conflating them is the most common design error
in this kind of application.

Interview practice lands here for the same reason. "Which dimension am I weakest
at, across every session, in the DevOps profile?" is an averaging question over
records, and the Progress dashboard is built entirely out of questions like it.
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime

from sqlalchemy import DateTime, Dialect, ForeignKey, Index, String, Text, TypeDecorator
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from career_copilot.core.types import ApplicationStatus

__all__ = [
    "Application",
    "Base",
    "InterviewAnswer",
    "InterviewSession",
    "Job",
    "MemoryFact",
    "ResponseFeedback",
    "UtcDateTime",
    "fact_fingerprint",
    "job_fingerprint",
]

_NOISE = re.compile(
    r"\b(gmbh|ag|se|kg|ltd|limited|inc|bv|nv|sarl|m/w/d|w/m/d|d/m/w|senior|sr|junior|jr)\b",
    re.IGNORECASE,
)
_NON_WORD = re.compile(r"[^\w\s]", re.UNICODE)


def job_fingerprint(company: str, title: str, location: str | None) -> str:
    """Stable id for deduplication across sources.

    The same role appears on several boards with cosmetic differences -
    "Senior DevOps Engineer / Bosch" versus "DevOps Engineer (m/w/d) /
    Robert Bosch GmbH". Normalising away the noise before hashing collapses them.
    """
    parts = [company or "", title or "", location or ""]
    normalised = " ".join(parts).lower()
    normalised = _NOISE.sub(" ", normalised)
    normalised = _NON_WORD.sub(" ", normalised)
    normalised = " ".join(normalised.split())
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()[:16]


def fact_fingerprint(text: str) -> str:
    """Stable id for one remembered fact, so the same one is never stored twice.

    Normalised the same way a job is: case, punctuation and spacing carry no
    meaning here. "Wants to stay in Stuttgart" and "wants to stay in Stuttgart."
    are one fact, and a model asked the same question on two days will phrase it
    both ways.
    """
    normalised = _NON_WORD.sub(" ", text.lower())
    normalised = " ".join(normalised.split())
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()[:16]


def _now() -> datetime:
    return datetime.now(UTC)


class UtcDateTime(TypeDecorator[datetime]):
    """Timezone-aware datetimes, even on SQLite.

    SQLite has no datetime type - it stores a string and throws the offset away,
    so a value written as aware comes back naive and comparing the two raises.
    Normalising to UTC on write and re-attaching it on read means every datetime
    that leaves the storage layer is aware, whatever the backend underneath.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC)


class Base(DeclarativeBase):
    pass


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    source: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(300))
    company: Mapped[str] = mapped_column(String(200))
    location: Mapped[str | None] = mapped_column(String(200), default=None)
    url: Mapped[str | None] = mapped_column(String(1000), default=None)
    description: Mapped[str] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(String(8), default=None)

    profile: Mapped[str | None] = mapped_column(String(40), default=None)
    fit_score: Mapped[float | None] = mapped_column(default=None)

    posted_at: Mapped[datetime | None] = mapped_column(UtcDateTime, default=None)
    first_seen_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_now)

    application: Mapped[Application | None] = relationship(
        back_populates="job", uselist=False, cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_jobs_profile_seen", "profile", "first_seen_at"),
        Index("ix_jobs_company", "company"),
    )


class Application(Base):
    """One row per job you have engaged with. Absence means "not yet triaged"."""

    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), unique=True)
    status: Mapped[str] = mapped_column(String(20), default=ApplicationStatus.INTERESTED)
    note: Mapped[str | None] = mapped_column(Text, default=None)
    cv_path: Mapped[str | None] = mapped_column(String(500), default=None)
    letter_path: Mapped[str | None] = mapped_column(String(500), default=None)

    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_now, onupdate=_now)

    job: Mapped[Job] = relationship(back_populates="application")

    __table_args__ = (Index("ix_applications_status", "status"),)


class InterviewSession(Base):
    """One sitting: a profile, a persona, and the answers that came out of it."""

    __tablename__ = "interview_sessions"

    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    profile: Mapped[str] = mapped_column(String(40))
    persona: Mapped[str] = mapped_column(String(40))
    difficulty: Mapped[str] = mapped_column(String(20))

    # Stored rather than re-read from the sidebar, so a session resumed after a
    # browser refresh is the same session it was: five questions asked of a
    # skeptical principal, not however the controls happen to be set now.
    planned_questions: Mapped[int] = mapped_column(default=5)

    # Practising for a specific posting is the useful case, but the session has
    # to outlive the posting - a job you no longer track should not delete the
    # record of how you performed against it. Hence SET NULL, not CASCADE.
    job_id: Mapped[str | None] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL"), default=None
    )

    started_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_now)
    ended_at: Mapped[datetime | None] = mapped_column(UtcDateTime, default=None)
    summary: Mapped[str | None] = mapped_column(Text, default=None)

    answers: Mapped[list[InterviewAnswer]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="InterviewAnswer.position",
    )

    __table_args__ = (Index("ix_sessions_profile_started", "profile", "started_at"),)


class InterviewAnswer(Base):
    """One question, one answer, five scores.

    The rubric dimensions are columns rather than a JSON blob or a child table.
    They are a fixed domain constant - the rubric IS these five things - and
    every question the Progress page asks is an average or a trend over one of
    them. `AVG(specificity) GROUP BY profile` is the whole feature; against JSON
    it would be a table scan in Python, and against a child table it would be a
    join for no gain. The cost is that changing the rubric is a migration, which
    is the correct amount of friction for changing what a score means.
    """

    __tablename__ = "interview_answers"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("interview_sessions.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column()

    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    is_probe: Mapped[bool] = mapped_column(default=False)

    # "typed" or "voice". Worth knowing: a spoken answer and a written one are
    # not the same performance, and comparing them without the label misleads.
    captured_as: Mapped[str] = mapped_column(String(10), default="typed")
    word_count: Mapped[int] = mapped_column(default=0)
    duration_seconds: Mapped[float | None] = mapped_column(default=None)

    structure: Mapped[float] = mapped_column(default=0.0)
    specificity: Mapped[float] = mapped_column(default=0.0)
    ownership: Mapped[float] = mapped_column(default=0.0)
    impact: Mapped[float] = mapped_column(default=0.0)
    relevance: Mapped[float] = mapped_column(default=0.0)

    feedback: Mapped[str | None] = mapped_column(Text, default=None)
    improved_answer: Mapped[str | None] = mapped_column(Text, default=None)
    answered_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_now)

    session: Mapped[InterviewSession] = relationship(back_populates="answers")

    __table_args__ = (Index("ix_answers_session_position", "session_id", "position"),)


class MemoryFact(Base):
    """Something durable the user said about their own search.

    Deliberately narrow. This is not a transcript and not a summary of the
    conversation - it is the handful of standing facts that change how the next
    answer should be written: what they are looking for, where, in what
    language, and what they will not accept.

    **Every row is deletable and every row says where it came from.** `origin`
    separates what the user stated outright from what the extractor inferred
    from a turn, because a user reviewing this page needs to know which of these
    they actually said. That distinction is also what makes deletion meaningful:
    it is their data, about their job search, and they get to correct it.

    `fingerprint` is unique, which is what stops the extractor re-storing the
    same fact on every turn that mentions it.
    """

    __tablename__ = "memory_facts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    fingerprint: Mapped[str] = mapped_column(String(16), unique=True)

    category: Mapped[str] = mapped_column(String(20))
    text: Mapped[str] = mapped_column(String(300))
    origin: Mapped[str] = mapped_column(String(10), default="extracted")

    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_now)
    # Bumped whenever a turn restates the fact. Recency is what decides which
    # facts survive the cap, so a preference mentioned once in April should not
    # outrank one repeated all week.
    last_seen_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_now)

    __table_args__ = (Index("ix_memory_category_seen", "category", "last_seen_at"),)


class ResponseFeedback(Base):
    """One rating the user gave one answer.

    Only rated turns are stored, and that is the whole design. The application
    keeps no transcript - `docs/memory.md` says so and means it - so a table
    that recorded every exchange in order to make ratings joinable would quietly
    turn this into the thing that page promises it is not. Storing the question
    and the answer *on the rating* keeps the row self-contained: a thumbs-down
    is readable months later without a transcript existing for the turns nobody
    rated.

    Both texts are masked before they arrive here, like everything else that
    reaches the store.

    `message_id` is unique because a rating is a current opinion, not a log.
    Changing your mind replaces the row rather than appending a second one, so
    the tally is always a count of answers rather than a count of clicks.
    """

    __tablename__ = "response_feedback"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    message_id: Mapped[str] = mapped_column(String(32), unique=True)
    thread_id: Mapped[str] = mapped_column(String(64))

    rating: Mapped[str] = mapped_column(String(8))
    mode: Mapped[str] = mapped_column(String(20))
    model: Mapped[str] = mapped_column(String(120))

    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_now)

    __table_args__ = (Index("ix_feedback_rating_created", "rating", "created_at"),)
