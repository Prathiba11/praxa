"""Fetch job postings into the local database.

    python scripts/fetch_jobs.py --source remotive --keywords kubernetes devops
    python scripts/fetch_jobs.py --source arbeitnow --location Stuttgart --pages 5
    python scripts/fetch_jobs.py --all-sources --keywords "site reliability"
    python scripts/fetch_jobs.py --url https://careers.example.com/jobs/1
    python scripts/fetch_jobs.py --stats

Safe to run repeatedly: postings are deduplicated by fingerprint, so a daily
run updates what changed and adds only what is new. That is what makes this
schedulable - a cron entry or a Task Scheduler job, with no state of its own.

Two sources, because neither is sufficient. Arbeitnow covers the German market
broadly but carries few engineering roles. Remotive is almost entirely
engineering but remote-only. Running both and letting deduplication sort it out
is cheaper than choosing.
"""

from __future__ import annotations

import argparse
import sys

from career_copilot.core.errors import CopilotError
from career_copilot.core.logging import configure_logging
from career_copilot.jobs import SOURCES, get_source, paste
from career_copilot.jobs.base import JobSource
from career_copilot.jobs.remotive import LEGAL_NOTICE
from career_copilot.jobs.sync import fetch_kwargs_for, save_posting, sync_source
from career_copilot.storage import jobs as repo
from career_copilot.storage.db import init_db


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch and store job postings.")
    parser.add_argument("--source", default="remotive", choices=sorted(SOURCES))
    parser.add_argument("--all-sources", action="store_true", help="run every source in turn")
    parser.add_argument("--keywords", nargs="*", default=[], help="search terms")
    parser.add_argument("--location", default=None, help="substring match on the location field")
    parser.add_argument("--remote-only", action="store_true", help="arbeitnow only")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--pages", type=int, default=3, help="arbeitnow only: pages to walk")
    parser.add_argument("--url", default=None, help="store one posting from a URL instead")
    parser.add_argument("--stats", action="store_true", help="show what is stored and exit")
    parser.add_argument(
        "--reclassify",
        action="store_true",
        help="re-run profile classification over stored jobs and exit",
    )
    return parser.parse_args(argv)


def _reclassify() -> int:
    """Apply the current classifier to rows stored under an older one.

    Worth having as a command rather than a database wipe: the application
    funnel lives in the same rows, and that is real data a heuristic change has
    no business destroying.
    """
    from career_copilot.jobs.base import classify_profile

    changed = 0
    jobs = repo.search_jobs(limit=1000)
    for job in jobs:
        before = job.profile
        after = classify_profile(job.title, job.description)
        if str(after or "") != str(before or ""):
            repo.set_profile(job.id, after)
            changed += 1
            print(f"  {job.title[:44]:<44} {before or '-'} -> {after or '-'}")

    print(f"\n{changed} of {len(jobs)} job(s) relabelled")
    return 0


def _stats() -> int:
    counts = repo.funnel_counts()
    print(f"{repo.count_jobs()} jobs stored")
    print("funnel: " + ", ".join(f"{status}={count}" for status, count in counts.items()))

    recent = repo.search_jobs(posted_since_days=7, limit=15)
    print(f"\n{len(recent)} seen in the last 7 days:")
    for job in recent:
        fit = f"fit {job.fit_score:.2f}" if job.fit_score is not None else "unscored"
        profile = job.profile or "no profile"
        print(f"  {job.id}  {job.title[:48]} - {job.company[:24]} ({profile}, {fit})")
    return 0


def _fetch_kwargs(args: argparse.Namespace, source: JobSource) -> dict[str, object]:
    """Only pass what a source understands - they do not share every filter.

    Which ones those are is read off the source's own signature rather than
    listed here, so a new source is wired in one place.
    """
    return fetch_kwargs_for(
        source,
        limit=args.limit,
        keywords=tuple(args.keywords),
        location=args.location,
        remote_only=args.remote_only,
        pages=args.pages,
    )


def _run(args: argparse.Namespace) -> int:
    configure_logging(level="WARNING")
    init_db()

    if args.stats:
        return _stats()

    if args.reclassify:
        return _reclassify()

    if args.url:
        posting = paste.from_url(args.url)
        job_id = save_posting(posting)
        print(f"stored {job_id}: {posting.title} - {posting.company}")
        print(f"profile: {posting.profile or 'unclassified'}  language: {posting.language}")
        return 0

    names = sorted(SOURCES) if args.all_sources else [args.source]
    total_fetched = 0
    total_unclassified = 0

    for name in names:
        source = get_source(name)
        report = sync_source(source, **_fetch_kwargs(args, source))
        print(report.summary())
        total_fetched += report.fetched
        total_unclassified += report.unclassified

    if "remotive" in names:
        print(f"\n{LEGAL_NOTICE}")

    if total_fetched == 0:
        print(
            "\nNothing matched. Try fewer keywords, drop --location, or "
            "--all-sources. Arbeitnow returns whole pages rather than search "
            "results, so a narrow filter over three pages often finds nothing."
        )
    elif total_unclassified:
        print(
            f"\n{total_unclassified} posting(s) stored without a profile, so a "
            f"profile-filtered search will not surface them. That is deliberate: "
            f"a wrong label hides a job more effectively than no label."
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        return _run(args)
    except CopilotError as exc:
        print(f"\nFAILED: {exc.user_message}\n  {exc.detail}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
