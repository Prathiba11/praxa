"""Repository for jobs and applications.

Everything that touches the database goes through here. Nothing above this layer
writes SQL, which is what keeps the "swap SQLite for Postgres later" promise
cheap.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from career_copilot.core.logging import get_logger
from career_copilot.core.types import ApplicationStatus, Profile
from career_copilot.storage.db import StorageError, session_scope
from career_copilot.storage.models import Application, Job, job_fingerprint

__all__ = [
    "count_jobs",
    "funnel_counts",
    "get_job",
    "list_applications",
    "search_jobs",
    "set_application_status",
    "set_fit_score",
    "set_profile",
    "upsert_job",
]

log = get_logger(__name__)


def upsert_job(
    *,
    source: str,
    title: str,
    company: str,
    description: str,
    location: str | None = None,
    url: str | None = None,
    posted_at: datetime | None = None,
    profile: Profile | None = None,
    language: str | None = None,
) -> Job:
    """Insert or update by fingerprint, so re-ingesting never duplicates."""
    job_id = job_fingerprint(company, title, location)

    with session_scope() as session:
        job = session.get(Job, job_id)
        if job is None:
            job = Job(
                id=job_id,
                source=source,
                title=title,
                company=company,
                location=location,
                url=url,
                description=description,
                posted_at=posted_at,
                profile=str(profile) if profile else None,
                language=language,
            )
            session.add(job)
            log.info("job added", extra={"job_id": job_id, "company": company})
        else:
            # Keep the earliest first_seen_at; refresh everything else.
            job.source = source
            job.title = title
            job.description = description
            job.location = location or job.location
            job.url = url or job.url
            job.posted_at = posted_at or job.posted_at
            job.language = language or job.language
            if profile:
                job.profile = str(profile)
        session.flush()
        session.expunge(job)
        return job


def get_job(job_id: str) -> Job | None:
    """Eager-loads the application row.

    Rows are detached before they leave this module, and a detached instance
    cannot lazy-load. Anything a caller might read has to be loaded here.
    """
    with session_scope() as session:
        job = session.scalar(
            select(Job).options(selectinload(Job.application)).where(Job.id == job_id)
        )
        if job is not None:
            session.expunge(job)
        return job


def search_jobs(
    *,
    profile: Profile | None = None,
    location: str | None = None,
    company: str | None = None,
    keywords: Sequence[str] | None = None,
    posted_since_days: int | None = None,
    min_fit: float | None = None,
    status: ApplicationStatus | None = None,
    include_unmatched: bool = False,
    limit: int = 20,
) -> list[Job]:
    """Deterministic filtering. Semantic "find me similar roles" is the vector
    store's job; this is counting and predicates, which SQL does exactly.

    `include_unmatched` controls the postings the classifier could not place in
    any profile. They are hidden by default: a job board answers a query with
    whatever is loosely related, and a list mixing three tracked careers with
    everything else is a list nobody reads.

    They are hidden rather than never stored, which is the important half. The
    classifier is keyword scoring with a required margin, so it rejects genuine
    matches written in unusual language. Discarding those at fetch time would
    lose them silently and leave no way to notice the classifier was wrong;
    keeping them means the count is visible, the rows can be inspected, and the
    vocabulary can be corrected from real examples.
    """
    with session_scope() as session:
        statement = select(Job).options(selectinload(Job.application))

        if profile:
            statement = statement.where(Job.profile == str(profile))
        elif not include_unmatched:
            # Only when no specific profile was asked for: naming a profile is
            # already a stronger filter than this one.
            statement = statement.where(Job.profile.is_not(None))
        if location:
            statement = statement.where(Job.location.ilike(f"%{location}%"))
        if company:
            statement = statement.where(Job.company.ilike(f"%{company}%"))
        if min_fit is not None:
            statement = statement.where(Job.fit_score >= min_fit)
        if posted_since_days is not None:
            cutoff = datetime.now(UTC) - timedelta(days=posted_since_days)
            statement = statement.where(Job.first_seen_at >= cutoff)
        if keywords:
            for word in keywords:
                statement = statement.where(
                    Job.description.ilike(f"%{word}%") | Job.title.ilike(f"%{word}%")
                )
        if status:
            statement = statement.join(Application).where(Application.status == str(status))

        statement = statement.order_by(
            Job.fit_score.desc().nullslast(), Job.first_seen_at.desc()
        ).limit(limit)

        jobs = list(session.scalars(statement))
        for job in jobs:
            session.expunge(job)
        return jobs


def count_jobs() -> int:
    with session_scope() as session:
        return int(session.scalar(select(func.count()).select_from(Job)) or 0)


def set_fit_score(job_id: str, score: float) -> None:
    """Cache a computed fit score so the next search can rank on it.

    Scoring costs an LLM call; ranking should not. Writing the number back is
    what turns "score this job" into "show me my best matches".
    """
    with session_scope() as session:
        job = session.get(Job, job_id)
        if job is None:
            return
        job.fit_score = score
        log.info("fit score stored", extra={"job_id": job_id, "fit_score": score})


def set_profile(job_id: str, profile: Profile | None) -> None:
    """Re-label a job.

    Classification is a heuristic and heuristics get improved. Being able to
    re-run it over stored rows means a fix does not require discarding the
    database - which matters, because the application funnel lives in the same
    rows and is real user data.
    """
    with session_scope() as session:
        job = session.get(Job, job_id)
        if job is None:
            return
        job.profile = str(profile) if profile else None


def set_application_status(
    job_id: str,
    status: ApplicationStatus,
    *,
    note: str | None = None,
    cv_path: str | None = None,
    letter_path: str | None = None,
) -> Application:
    """Create or update the application row for a job.

    The job must exist. Checked explicitly rather than left to the foreign key,
    so a mistyped id from a tool call produces a readable message instead of an
    IntegrityError - and so the failure is the same on any backend.
    """
    with session_scope() as session:
        if session.get(Job, job_id) is None:
            raise StorageError(f"no job stored with id {job_id!r}")

        application = session.scalar(select(Application).where(Application.job_id == job_id))
        if application is None:
            application = Application(job_id=job_id, status=str(status))
            session.add(application)
        else:
            application.status = str(status)

        if note is not None:
            application.note = note
        if cv_path is not None:
            application.cv_path = cv_path
        if letter_path is not None:
            application.letter_path = letter_path

        session.flush()
        session.expunge(application)
        log.info("application updated", extra={"job_id": job_id, "status": str(status)})
        return application


def list_applications(status: ApplicationStatus | None = None) -> list[Application]:
    with session_scope() as session:
        statement = (
            select(Application)
            .options(selectinload(Application.job))
            .order_by(Application.updated_at.desc())
        )
        if status:
            statement = statement.where(Application.status == str(status))
        rows = list(session.scalars(statement))
        for row in rows:
            session.expunge(row)
        return rows


def funnel_counts() -> dict[str, int]:
    """Applications per status - the Progress dashboard's headline figures."""
    with session_scope() as session:
        rows = session.execute(
            select(Application.status, func.count()).group_by(Application.status)
        ).all()
        counts = {str(status): int(count) for status, count in rows}
        return {str(s): counts.get(str(s), 0) for s in ApplicationStatus}
