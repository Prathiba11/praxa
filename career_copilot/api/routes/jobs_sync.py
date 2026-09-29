"""Fetching live postings, from the browser.

This is the endpoint that should have existed from the start. The job sources
have been in the project since the previous version - Arbeitnow and Remotive,
both public APIs rather than scrapers, because the large boards forbid automated
collection - and `scripts/fetch_jobs.py` has always been able to pull from them.
What was missing was any way to do it from the application, so a fresh install
showed an empty Jobs page and the only way to fill it was a command line.

**Why the two sources, and why an API rather than a scraper.** LinkedIn, Xing
and Indeed all prohibit automated collection in their terms; a project with
someone's name on it should not quietly break them. Arbeitnow publishes a free,
unauthenticated job-board API and is strong on the German market, which is the
market this application is for. Remotive covers remote roles. Anything neither
carries can still be pasted in by hand.

**It runs on a worker thread.** Fetching is blocking HTTP against someone else's
server, and doing that on the event loop would freeze every other request for
as long as the board takes to answer.
"""

from __future__ import annotations

import asyncio
from time import monotonic

from fastapi import APIRouter, HTTPException
from pydantic import Field

from career_copilot.api.schemas import Camel
from career_copilot.core.errors import CopilotError
from career_copilot.core.logging import get_logger
from career_copilot.jobs import SOURCES, get_source
from career_copilot.jobs.sync import fetch_kwargs_for, sync_source

__all__ = ["router"]

log = get_logger(__name__)

router = APIRouter(tags=["jobs"], prefix="/jobs")


class SyncRequest(Camel):
    #: Which board. Empty means every source the project knows about.
    source: str | None = None
    limit: int = Field(default=30, ge=1, le=100)
    #: Words the posting must contain. Remotive's own search parameter is
    #: unreliable - it returns the same page for different terms - so keyword
    #: filtering happens client-side inside the source.
    keywords: list[str] = Field(default_factory=list, max_length=8)
    location: str | None = Field(default=None, max_length=80)
    remote_only: bool = False


class SourceReport(Camel):
    source: str
    fetched: int
    added: int
    updated: int
    #: Postings the classifier could not assign to a profile. Reported rather
    #: than hidden: the classification is a heuristic and says so.
    unclassified: int
    error: str | None = None


class SyncResult(Camel):
    reports: list[SourceReport]
    added: int
    message: str


@router.get("/sources", response_model=list[str])
def list_sources() -> list[str]:
    """Which boards this install can fetch from."""
    return sorted(SOURCES)


@router.post("/sync", response_model=SyncResult)
async def sync_jobs(payload: SyncRequest) -> SyncResult:
    """Pull postings from the job boards and store them."""
    names = [payload.source] if payload.source else sorted(SOURCES)
    unknown = [name for name in names if name not in SOURCES]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown job source: {unknown[0]}")

    def work() -> list[SourceReport]:
        out: list[SourceReport] = []
        for name in names:
            # Timed per source. "The fetch takes forever" is not actionable;
            # "arbeitsagentur took 94s and the other two took 3s" is.
            started = monotonic()
            try:
                source = get_source(name)
                report = sync_source(
                    source,
                    # Filtered to what this source accepts: passing the union
                    # of every filter raises TypeError, which is not a
                    # CopilotError and would fail the whole request rather
                    # than the one board.
                    **fetch_kwargs_for(
                        source,
                        limit=payload.limit,
                        keywords=tuple(payload.keywords),
                        location=payload.location,
                        remote_only=payload.remote_only,
                    ),
                )
            except CopilotError as exc:
                # One board being down must not lose the postings another one
                # returned, so a failure is reported per source rather than
                # failing the whole request.
                log.warning(
                    "job source failed",
                    extra={
                        "source": name,
                        "detail": exc.detail,
                        "seconds": round(monotonic() - started, 1),
                    },
                )
                out.append(
                    SourceReport(
                        source=name,
                        fetched=0,
                        added=0,
                        updated=0,
                        unclassified=0,
                        error=exc.user_message,
                    )
                )
                continue

            log.info(
                "job source finished",
                extra={
                    "source": name,
                    "seconds": round(monotonic() - started, 1),
                    "fetched": report.fetched,
                    "added": report.added,
                },
            )
            out.append(
                SourceReport(
                    source=report.source,
                    fetched=report.fetched,
                    added=report.added,
                    updated=report.updated,
                    unclassified=report.unclassified,
                )
            )
        return out

    reports = await asyncio.to_thread(work)
    added = sum(report.added for report in reports)
    failed = [report.source for report in reports if report.error]

    if failed and added == 0:
        message = f"Could not reach {' or '.join(failed)}. Nothing was added."
    elif failed:
        message = f"Added {added} new postings. {' and '.join(failed)} could not be reached."
    elif added == 0:
        message = "Nothing new — every posting returned was already saved."
    else:
        message = f"Added {added} new postings."

    log.info("job sync finished", extra={"added": added, "sources": names})
    return SyncResult(reports=reports, added=added, message=message)
