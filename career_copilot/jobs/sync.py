"""Turning postings into rows.

The only place that bridges a source and the database. Everything arriving here
is already normalised, so this is deliberately dull: upsert each posting, count
what happened, report it.

Counting new against updated is done by comparing row counts around the write
rather than by asking `upsert_job` to report. That keeps the repository's
signature honest - it performs an upsert, and an upsert does not naturally know
whether you consider the result new.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any, cast

from career_copilot.core.logging import get_logger
from career_copilot.jobs.base import JobPosting, JobSource
from career_copilot.storage import jobs as repo
from career_copilot.storage.db import init_db

__all__ = ["SyncReport", "fetch_kwargs_for", "save_posting", "sync_source"]

log = get_logger(__name__)


@dataclass(frozen=True)
class SyncReport:
    source: str
    fetched: int
    added: int
    updated: int
    unclassified: int

    def summary(self) -> str:
        return (
            f"{self.source}: {self.fetched} fetched, {self.added} new, "
            f"{self.updated} already known, {self.unclassified} without a profile"
        )


def save_posting(posting: JobPosting) -> str:
    """Store one posting and return its id. Idempotent by fingerprint."""
    init_db()
    job = repo.upsert_job(
        source=posting.source,
        title=posting.title,
        company=posting.company,
        description=posting.description,
        location=posting.location,
        url=posting.url,
        posted_at=posting.posted_at,
        profile=posting.profile,
        language=posting.language,
    )
    return job.id


def fetch_kwargs_for(source: JobSource, **requested: object) -> dict[str, object]:
    """Keep only the filters this source actually takes.

    The sources do not share every filter - `remote_only` means something to
    Arbeitnow and nothing to the others - and a caller that sends the union of
    them all gets a `TypeError`, which is not a `CopilotError` and so escapes
    the per-source error handling and fails the whole request.

    Reading the signature rather than keeping a table of source names means a
    new source cannot reintroduce that bug by being added in one place and
    forgotten in another.
    """
    parameters = inspect.signature(source.fetch).parameters
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in parameters.values()):
        return dict(requested)
    return {name: value for name, value in requested.items() if name in parameters}


def sync_source(source: JobSource, **fetch_kwargs: object) -> SyncReport:
    """Fetch from a source and write everything it returns.

    Raises:
        JobSourceError: the source failed. Nothing is written in that case,
            because the fetch completes before the first write.
    """
    init_db()
    postings = source.fetch(**cast(Any, fetch_kwargs))

    before = repo.count_jobs()
    for posting in postings:
        save_posting(posting)
    added = repo.count_jobs() - before

    report = SyncReport(
        source=source.name,
        fetched=len(postings),
        added=added,
        updated=len(postings) - added,
        unclassified=sum(1 for posting in postings if posting.profile is None),
    )
    log.info("sync complete", extra={"source": source.name, "added": added})
    return report
