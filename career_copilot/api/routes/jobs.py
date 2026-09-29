"""Saved postings and where each one has got to.

**This router does not think.** It lists, filters, opens and moves rows. Every
judgement a user might want - is this a good fit, what would a tailored CV say,
what is missing - is an agent tool, reachable from chat in `jobs` mode. That is
a deliberate split: those tools already exist, they already carry the mode's
permissions, and a second implementation behind an endpoint would be a second
thing to keep correct and the first thing to drift.

So nothing here spends money. Every call is a SQL query, which is why the page
stays instant while the agent takes its seconds.
"""

from __future__ import annotations

from typing import cast, get_args

from fastapi import APIRouter, HTTPException, Query

from career_copilot.api.schemas import (
    ApplicationStatusValue,
    FitOut,
    FunnelCounts,
    JobDetail,
    JobSummary,
    PasteJobRequest,
    ProfileValue,
    SetStatusRequest,
)
from career_copilot.core.errors import CopilotError
from career_copilot.core.logging import get_logger
from career_copilot.core.session import use_session
from career_copilot.core.types import ApplicationStatus, Profile
from career_copilot.core.usage import new_session_id
from career_copilot.jobs.base import JobPosting, classify_profile, detect_language
from career_copilot.jobs.paste import title_and_company_from_text
from career_copilot.jobs.sync import save_posting
from career_copilot.storage import jobs as repo
from career_copilot.storage.db import init_db
from career_copilot.storage.models import Job
from career_copilot.tools.fit import score_posting

__all__ = ["router"]

log = get_logger(__name__)

router = APIRouter(tags=["jobs"], prefix="/jobs")

#: What a posting the user pasted in is attributed to. Fixed rather than taken
#: from the request: attribution is a licence condition on the boards this
#: application reads, so "where did this come from" must not be client-supplied.
PASTED_SOURCE = "pasted"


#: The database stores these as plain strings, and the API promises a closed
#: set. Narrowing through the enum is what makes the promise true: a value that
#: is not a member raises here, at the boundary, rather than reaching a client
#: that has no branch for it.
_STATUSES: frozenset[str] = frozenset(str(s) for s in ApplicationStatus)
_PROFILES: frozenset[str] = frozenset(str(p) for p in Profile)


def _status_of(job: Job) -> ApplicationStatusValue | None:
    application = job.application
    if application is None or application.status not in _STATUSES:
        return None
    return ApplicationStatus(application.status).value


def _profile_of(job: Job) -> ProfileValue | None:
    """A posting the classifier could not place has no profile, which is a
    real state - not every job is one of the three."""
    if job.profile is None or job.profile not in _PROFILES:
        return None
    return Profile(job.profile).value


def _summary(job: Job) -> JobSummary:
    return JobSummary(
        id=job.id,
        title=job.title,
        company=job.company,
        location=job.location,
        url=job.url,
        source=job.source,
        profile=_profile_of(job),
        fit_score=job.fit_score,
        status=_status_of(job),
        posted_at=job.posted_at,
        first_seen_at=job.first_seen_at,
    )


@router.get("", response_model=list[JobSummary])
def list_jobs(
    profile: ProfileValue | None = None,
    location: str | None = None,
    company: str | None = None,
    status: ApplicationStatusValue | None = None,
    query: str | None = Query(default=None, description="Words that must appear in title or text"),
    min_fit: float | None = Query(
        default=None,
        ge=0.0,
        le=100.0,
        alias="minFit",
        description="Percentage, 0-100. Stored scores are fractions, so this is converted.",
    ),
    include_unmatched: bool = Query(
        default=False,
        alias="includeUnmatched",
        description="Also return postings the classifier could not place in a profile.",
    ),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[JobSummary]:
    """Postings matching every filter given, best fit first.

    Deliberately predicates rather than similarity. "Find me something like
    this one" is the vector store's question; "Stuttgart, DevOps, not yet
    applied" is SQL's, and SQL answers it exactly rather than approximately.
    """
    init_db()
    keywords = query.split() if query else None

    # The filter speaks percentages because that is what the number on a card
    # says; `Job.fit_score` holds the 0-1 fraction the model produced. Without
    # this conversion the filter compared 70 against 0.7 and matched nothing.
    min_fraction = min_fit / 100 if min_fit is not None else None

    jobs = repo.search_jobs(
        profile=Profile(profile) if profile else None,
        location=location,
        company=company,
        keywords=keywords,
        min_fit=min_fraction,
        status=ApplicationStatus(status) if status else None,
        include_unmatched=include_unmatched,
        limit=limit,
    )
    return [_summary(job) for job in jobs]


@router.get("/funnel", response_model=FunnelCounts)
def funnel() -> FunnelCounts:
    """How many applications sit at each stage.

    Declared before `/{job_id}`: FastAPI matches routes in order, and without
    that this path would be read as a job whose id is "funnel".
    """
    init_db()
    return FunnelCounts(counts=repo.funnel_counts(), total_jobs=repo.count_jobs())


@router.get("/{job_id}", response_model=JobDetail)
def get_job(job_id: str) -> JobDetail:
    init_db()
    job = repo.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="No such job.")

    application = job.application
    return JobDetail(
        **_summary(job).model_dump(),
        description=job.description,
        language=job.language,
        note=application.note if application else None,
        cv_path=application.cv_path if application else None,
        letter_path=application.letter_path if application else None,
    )


@router.post("/{job_id}/status", response_model=JobDetail)
def set_status(job_id: str, payload: SetStatusRequest) -> JobDetail:
    """Move an application along the funnel.

    A status is a fact about what the user did, so it is set by the user here
    and by the agent only when the user says so in as many words - see the
    jobs-mode rule in `agent.loop`. Nothing infers it.
    """
    init_db()
    if repo.get_job(job_id) is None:
        raise HTTPException(status_code=404, detail="No such job.")

    repo.set_application_status(job_id, ApplicationStatus(payload.status), note=payload.note)
    log.info("application status set", extra={"job_id": job_id, "status": payload.status})
    return get_job(job_id)


def _profile_value(value: str) -> ProfileValue:
    """Narrow a stored profile string to the Literal the API promises.

    The column is plain text, so a row written by an older version could hold
    anything. Failing loudly here beats serialising a value the client's type
    says cannot exist.
    """
    if value not in get_args(ProfileValue):
        raise HTTPException(status_code=500, detail=f"stored profile {value!r} is not a known one")
    return cast(ProfileValue, value)


@router.post("/{job_id}/score", response_model=FitOut)
def score_job(job_id: str) -> FitOut:
    """Score one posting against the CV for its track, and cache the number.

    This is the one endpoint on this router that costs money and takes seconds,
    and it exists because the alternative was telling the user to leave the page
    and ask the agent. The agent still can; this is the same tool called
    directly, so there is one implementation and one set of rules.

    The posting must already be classified. A job the classifier could not place
    has no CV to score against, and guessing one would produce a confident
    number with nothing behind it - which is exactly the failure this project
    spends its evaluation section arguing against.
    """
    init_db()
    job = repo.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="No such posting.")
    if not job.profile:
        raise HTTPException(
            status_code=409,
            detail="This posting is not matched to one of your tracks, so there is no CV to score it against.",
        )

    # A fresh session id: this is a model call outside any chat thread, and the
    # usage ledger refuses unattributed calls.
    with use_session(new_session_id()):
        try:
            report = score_posting(Profile(job.profile), job.description or "", job_id=job.id)
        except CopilotError as exc:
            log.warning("scoring failed", extra={"job_id": job_id, "detail": exc.detail})
            raise HTTPException(status_code=502, detail=exc.user_message) from exc

    log.info("job scored", extra={"job_id": job_id, "score": report.score})
    return FitOut(
        profile=_profile_value(job.profile),
        score=report.score,
        matched=report.matched,
        missing=report.missing,
        blockers=report.blockers,
        conflicts=report.conflicts,
        verdict=report.verdict,
    )


@router.post("/paste", response_model=JobDetail, status_code=201)
def paste_job(payload: PasteJobRequest) -> JobDetail:
    """Save a posting copied out of a browser.

    Idempotent by fingerprint: pasting the same posting twice updates the row
    rather than creating a second one, so a user who pastes the same job from
    two boards does not end up scoring it twice.

    A paste is classified and language-detected here exactly as a fetched
    posting is. It was not, and the result was a posting saved with no profile
    at all - which the list hides by default, so pasting appeared to succeed
    and then the job was nowhere to be found. An explicit choice in the form
    still wins over the classifier; the classifier only fills a blank.
    """
    init_db()
    description = payload.description.strip()

    # Only the text is required. Anything the user did not fill in is read out
    # of the paste, and falls back to a placeholder rather than a guess.
    read_title, read_company = title_and_company_from_text(description)
    title = (payload.title or "").strip() or read_title or "Untitled role"
    company = (payload.company or "").strip() or read_company or "Unknown company"

    profile = Profile(payload.profile) if payload.profile else classify_profile(title, description)

    job_id = save_posting(
        JobPosting(
            source=PASTED_SOURCE,
            title=title,
            company=company,
            description=description,
            location=payload.location,
            url=payload.url,
            language=detect_language(f"{title}\n{description}"),
            profile=profile,
        )
    )
    log.info(
        "posting pasted",
        extra={"job_id": job_id, "company": company, "profile": profile},
    )
    return get_job(job_id)
