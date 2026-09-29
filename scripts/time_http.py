"""Time the individual HTTP requests behind each job source.

`time_sources.py` said Arbeitnow and Remotive cost about 60 seconds each while
the Bundesagentur costs 1.4. That is the what; this is the why. A round 60 can
mean a timeout being hit, a very large body, or a genuinely slow server, and
those need different fixes - so this reports the phases separately rather than
one total.

Nothing is written to the database and nothing is parsed into postings.

    python scripts/time_http.py
"""

from __future__ import annotations

import sys
from time import monotonic

import httpx

from career_copilot.jobs.arbeitnow import API_URL as ARBEITNOW_URL
from career_copilot.jobs.arbeitsagentur import API_KEY
from career_copilot.jobs.arbeitsagentur import SEARCH_URL as BA_URL
from career_copilot.jobs.remotive import API_URL as REMOTIVE_URL

_BA_HEADERS = {"X-API-Key": API_KEY, "User-Agent": "career-copilot/1.0 (student project)"}

_REQUESTS: list[tuple[str, str, dict[str, str], dict[str, str]]] = [
    ("arbeitnow page 1", ARBEITNOW_URL, {"page": "1"}, {}),
    ("arbeitnow page 2", ARBEITNOW_URL, {"page": "2"}, {}),
    ("remotive", REMOTIVE_URL, {"limit": "40", "category": "software-dev"}, {}),
    ("bundesagentur", BA_URL, {"was": "DevOps Engineer", "size": "10"}, _BA_HEADERS),
]


def main() -> int:
    print(f"{'request':<20} {'status':>6} {'total s':>8} {'first byte':>11} {'KB':>8} {'items':>7}")
    print("-" * 68)

    for label, url, params, headers in _REQUESTS:
        started = monotonic()
        try:
            with (
                httpx.Client(timeout=90.0) as client,
                client.stream("GET", url, params=params, headers=headers) as response,
            ):
                first_byte = monotonic() - started
                body = response.read()
        except httpx.HTTPError as exc:
            print(f"{label:<20} {'ERR':>6}  {type(exc).__name__}: {exc}")
            continue

        total = monotonic() - started
        kb = len(body) / 1024
        items = "-"
        try:
            payload = response.json()
            for key in ("data", "jobs", "ergebnisliste", "stellenangebote"):
                value = payload.get(key) if isinstance(payload, dict) else None
                if isinstance(value, list):
                    items = str(len(value))
                    break
        except ValueError:
            pass

        print(
            f"{label:<20} {response.status_code:>6} {total:>8.1f} "
            f"{first_byte:>11.1f} {kb:>8.0f} {items:>7}"
        )

    print()
    print("'first byte' is how long the server thought before answering.")
    print("A high first byte with a small body means a slow server.")
    print("A low first byte with a large body means we are downloading too much.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
