"""Job-record tools: deterministic search and funnel updates.

These questions - "which Stuttgart roles mention Terraform", "how many have I
applied to" - have exact answers, so they go to SQL. Asking a vector store to
count is how you get a confident wrong number.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from career_copilot.core.types import ApplicationStatus, Profile
from career_copilot.storage import jobs as jobs_repo
from career_copilot.storage.models import Job
from career_copilot.tools.base import Tool

__all__ = [
    "SearchJobsArgs",
    "SetApplicationStatusArgs",
    "search_jobs",
    "set_application_status",
]

_MAX_SNIPPET = 180


class SearchJobsArgs(BaseModel):
    profile: Profile | None = Field(default=None, description="Restrict to one career profile.")
    location: str | None = Field(default=None, description="Substring match, e.g. 'Stuttgart'.")
    company: str | None = Field(default=None, description="Substring match on employer name.")
    keywords: list[str] | None = Field(
        default=None,
        max_length=8,
        description="All keywords must appear in the title or description.",
    )
    posted_since_days: int | None = Field(
        default=None, ge=1, le=365, description="Only jobs first seen within this many days."
    )
    min_fit: float | None = Field(
        default=None, ge=0.0, le=1.0, description="Only jobs already scored at or above this."
    )
    status: ApplicationStatus | None = Field(
        default=None, description="Only jobs at this stage of the application funnel."
    )
    limit: int = Field(default=10, ge=1, le=50)


def _format(job: Job, position: int) -> str:
    bits = [f"{position}. {job.title} - {job.company}"]
    if job.location:
        bits.append(f"({job.location})")
    line = " ".join(bits)

    facts = [f"id={job.id}", f"source={job.source}"]
    if job.profile:
        facts.append(f"profile={job.profile}")
    if job.fit_score is not None:
        facts.append(f"fit={job.fit_score:.2f}")
    if job.application is not None:
        facts.append(f"status={job.application.status}")

    snippet = " ".join(job.description.split())[:_MAX_SNIPPET]
    return f"{line}\n   {' | '.join(facts)}\n   {snippet}..."


def _run_search(args: SearchJobsArgs) -> str:
    found = jobs_repo.search_jobs(
        profile=args.profile,
        location=args.location,
        company=args.company,
        keywords=args.keywords,
        posted_since_days=args.posted_since_days,
        min_fit=args.min_fit,
        status=args.status,
        limit=args.limit,
    )
    if not found:
        return "No stored jobs match those filters."

    header = f"{len(found)} matching job(s), best fit first:"
    return header + "\n" + "\n".join(_format(job, i) for i, job in enumerate(found, start=1))


class SetApplicationStatusArgs(BaseModel):
    job_id: str = Field(description="The id shown by search_jobs.", min_length=4, max_length=32)
    status: ApplicationStatus = Field(description="New stage in the application funnel.")
    note: str | None = Field(
        default=None, max_length=1000, description="Optional short note, e.g. recruiter name."
    )


def _run_status(args: SetApplicationStatusArgs) -> str:
    application = jobs_repo.set_application_status(args.job_id, args.status, note=args.note)
    return f"Job {args.job_id} is now '{application.status}'."


search_jobs = Tool(
    name="search_jobs",
    description="""
        Search saved job postings by exact filters: profile, location, company,
        keywords, recency, fit score, application status. Use this for anything
        countable or filterable. Returns job ids you can pass to the other tools.
    """,
    args_model=SearchJobsArgs,
    handler=_run_search,
)

set_application_status = Tool(
    name="set_application_status",
    description="""
        Move a saved job to a new stage of the application funnel (interested,
        applied, screening, interview, offer, rejected, withdrawn). Only call this
        when the user explicitly says the stage changed.
    """,
    args_model=SetApplicationStatusArgs,
    handler=_run_status,
)
