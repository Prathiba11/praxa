"""Read the real shape of the v6 Jobsuche response before coding against it.

The first probe established what works: `/pc/v6/jobs`, with the key, with an
ordinary honest User-Agent. Every `/pc/v4/app/...` variant returned 403 for
everyone, including the agency's own app string, so that path is simply closed
rather than gated - which also settles the question of whether using this
endpoint means impersonating their client. It does not.

What is still unknown is the shape. v6 calls its results `ergebnisliste`, not
`stellenangebote`, so the other field names are unknown too - and the important
question is whether a search result carries the posting text or whether a
second call is needed for it.

This prints the keys rather than assuming them.

    python scripts/probe_arbeitsagentur.py
"""

from __future__ import annotations

import base64
import json
import sys

import httpx

from career_copilot.jobs.arbeitsagentur import API_KEY

_V6_URL = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v6/jobs"
_DETAILS = (
    "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4/jobdetails/{code}",
    "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v3/jobdetails/{code}",
)
_HEADERS = {"X-API-Key": API_KEY, "User-Agent": "career-copilot/1.0 (student project)"}
_PARAMS = {"was": "DevOps Engineer", "wo": "Stuttgart", "umkreis": "50", "size": "3"}


def _show_detail(client: httpx.Client, reference: str) -> None:
    code = base64.b64encode(reference.encode()).decode()
    for template in _DETAILS:
        version = "v4" if "/v4/" in template else "v3"
        try:
            detail = client.get(template.format(code=code))
        except httpx.HTTPError as exc:
            print(f"detail {version}: ERROR {type(exc).__name__}: {exc}")
            continue
        print(f"detail {version}: {detail.status_code}")
        if detail.status_code != 200:
            continue
        body = detail.json()
        if not isinstance(body, dict):
            continue
        print(f"  keys: {sorted(body)[:25]}")
        for key, value in body.items():
            if isinstance(value, str) and len(value) > 200:
                print(f"  {key}: {len(value)} chars  <- the posting text")


def main() -> int:
    with httpx.Client(timeout=30.0, headers=_HEADERS) as client:
        response = client.get(_V6_URL, params=_PARAMS)
        print(f"search status: {response.status_code}")
        if response.status_code != 200:
            print(response.text[:400])
            return 1

        payload = response.json()
        print(f"top-level keys: {sorted(payload)}\n")

        results = payload.get("ergebnisliste") or []
        if not results:
            for key, value in payload.items():
                if isinstance(value, list) and value:
                    print(f"(results appear to be under {key!r} instead)")
                    results = value
                    break
        if not results:
            print("No results at all. Try a broader search term.")
            return 1

        first = results[0]
        print(f"records: {len(results)}")
        print(f"record keys: {sorted(first)}\n")
        print("first record, in full:")
        print(json.dumps(first, indent=2, ensure_ascii=False)[:2500])

        print("\n" + "=" * 70)
        print("Fields long enough to be the posting text (none means a detail call is needed):")
        for key, value in first.items():
            if isinstance(value, str) and len(value) > 200:
                print(f"  {key}: {len(value)} chars")

        reference = first.get("refnr") or first.get("referenznummer") or first.get("hashId")
        print(f"\nreference field value: {reference!r}")
        if not reference:
            print("No reference number - cannot try the detail endpoints.")
            return 0
        print()
        _show_detail(client, str(reference))
    return 0


if __name__ == "__main__":
    sys.exit(main())
