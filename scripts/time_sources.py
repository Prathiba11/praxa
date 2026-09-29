"""Time each job source separately, so "the fetch is slow" becomes a number.

Nothing is written to the database. Run it, read the table, and the slow source
names itself.

    python scripts/time_sources.py
"""

from __future__ import annotations

import sys
from time import monotonic

from career_copilot.core.errors import CopilotError
from career_copilot.core.logging import configure_logging
from career_copilot.jobs import SOURCES, get_source
from career_copilot.jobs.sync import fetch_kwargs_for


def main() -> int:
    configure_logging(level="WARNING")
    print(f"{'source':<18} {'seconds':>8}  {'postings':>8}  note")
    print("-" * 74)

    total = 0.0
    for name in sorted(SOURCES):
        source = get_source(name)

        # A generous deadline on purpose. The app caps arbeitsagentur at 25s,
        # and measuring against that cap would only ever report 25s. What is
        # wanted here is the true cost, so the cap is lifted for the reading.
        kwargs = fetch_kwargs_for(source, limit=20, keywords=(), location=None, max_seconds=180.0)

        started = monotonic()
        try:
            postings = source.fetch(**kwargs)
        except CopilotError as exc:
            elapsed = monotonic() - started
            total += elapsed
            print(f"{name:<18} {elapsed:>8.1f}  {'-':>8}  FAILED: {exc.detail[:40]}")
            continue

        elapsed = monotonic() - started
        total += elapsed
        matched = sum(1 for posting in postings if posting.profile is not None)
        print(f"{name:<18} {elapsed:>8.1f}  {len(postings):>8}  {matched} matched to a track")

    print("-" * 74)
    print(f"{'total':<18} {total:>8.1f}")
    print("\nThis is the true cost per source. In the app, arbeitsagentur is")
    print("capped at 25 seconds and returns whatever it has by then.")
    print("Anything not a CopilotError is left to crash with its traceback -")
    print("a diagnostic that swallows the exception tells you nothing.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
