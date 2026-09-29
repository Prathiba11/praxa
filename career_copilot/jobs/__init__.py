"""Job sources: fetching postings and normalising them into storage.

Three sources, because none covers the ground alone. Arbeitnow is the German
market, broad but shallow on engineering. Remotive is engineering, deep but
remote-only. Arbeitsagentur is the largest German database by far and the only
one that reliably surfaces Stuttgart automotive roles, at the cost of an
unofficial endpoint - `arbeitsagentur.py` states that cost in full rather than
burying it. `SOURCES` is what the CLI and the UI choose from; adding a fourth
means adding a class and one entry here.
"""

from career_copilot.jobs.arbeitnow import ArbeitnowSource
from career_copilot.jobs.arbeitsagentur import ArbeitsagenturSource
from career_copilot.jobs.base import (
    JobPosting,
    JobSource,
    JobSourceError,
    classify_profile,
    detect_language,
    html_to_text,
)
from career_copilot.jobs.remotive import RemotiveSource
from career_copilot.jobs.sync import SyncReport, save_posting, sync_source

__all__ = [
    "SOURCES",
    "ArbeitnowSource",
    "ArbeitsagenturSource",
    "JobPosting",
    "JobSource",
    "JobSourceError",
    "RemotiveSource",
    "SyncReport",
    "classify_profile",
    "detect_language",
    "get_source",
    "html_to_text",
    "save_posting",
    "sync_source",
]

SOURCES: dict[str, type] = {
    ArbeitnowSource.name: ArbeitnowSource,
    ArbeitsagenturSource.name: ArbeitsagenturSource,
    RemotiveSource.name: RemotiveSource,
}


def get_source(name: str) -> JobSource:
    """Build a source by name. Raises JobSourceError for an unknown one."""
    factory = SOURCES.get(name)
    if factory is None:
        raise JobSourceError(f"unknown source {name!r} - available: {sorted(SOURCES)}")
    source: JobSource = factory()
    return source
