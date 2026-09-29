"""Bundesagentur fuer Arbeit (Jobboerse) source - the German market, properly.

**What this is, stated plainly.** The Bundesagentur fuer Arbeit runs the largest
database of open positions in Germany and publishes no official API for it. The
endpoint used here is the one its own Jobsuche mobile app calls, with the fixed
key that app ships. It is documented by the bundesAPI community project rather
than by the agency, and no terms of use are published alongside it.

That is a weaker footing than Arbeitnow and Remotive, which publish APIs meant
to be called, and the difference is recorded here rather than hidden. It is
still a very different thing from scraping LinkedIn or Indeed, which forbid
automated collection outright: this is a public, unauthenticated, read-only
endpoint serving data the agency publishes for the public to read. The request
rate is one search per track plus one detail lookup per candidate, bounded by
`limit` - a few dozen requests, not a crawl.

**Two calls per posting, and why.** The search endpoint returns a summary only:
occupation, employer, place, reference number. The text a CV gets scored against
lives behind a second call, `jobdetails/{encryptedJobCode}`, where the code is
the base64 of the reference number. So this source is N+1 by the API's design,
not by choice, and `DETAIL_BUDGET` caps how many details a single fetch will
spend.

**Unclassified postings are dropped here, unlike the other sources.** Arbeitnow
and Remotive are fetched broadly and classified afterwards, so a posting with no
profile is a genuine "we do not know". This source is queried *per track* - the
search term names the profile - so a result that still fails to classify is a
search miss, and keeping it would quietly widen the board past the three tracks
it is supposed to hold.
"""

from __future__ import annotations

import base64
from collections.abc import Iterable
from datetime import UTC, datetime
from time import monotonic
from typing import Any
from urllib.parse import quote

import httpx

from career_copilot.core.logging import get_logger
from career_copilot.core.types import Profile
from career_copilot.jobs.base import (
    JobPosting,
    JobSourceError,
    build_client,
    classify_profile,
    detect_language,
    html_to_text,
)

__all__ = [
    "API_KEY",
    "DETAIL_BUDGET",
    "DETAIL_URL",
    "SEARCH_URL",
    "TRACK_TERMS",
    "ArbeitsagenturSource",
]

log = get_logger(__name__)

# v6, not the v4 "app" path. Every v4/app variant answers 403 to everyone now,
# including requests carrying the agency's own app User-Agent - so that path is
# closed rather than gated, and using v6 with an honest User-Agent is not
# pretending to be their client. A probe against the live endpoint established
# this; `scripts/probe_arbeitsagentur.py` reproduces it.
SEARCH_URL = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v6/jobs"
DETAIL_URL = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4/jobdetails/{code}"

# The published community spec names the result list `stellenangebote`. The live
# v6 endpoint returns `ergebnisliste`. Both are accepted because the spec has
# already been wrong once, and a source that dies on a renamed key is a source
# that dies silently.
_RESULT_KEYS = ("ergebnisliste", "stellenangebote")

# Same reasoning for the fields. The names below are what the live v6 endpoint
# actually returns, read off a real response - the published spec named almost
# none of them correctly. The spec's names are kept as fallbacks rather than
# deleted, because being wrong in one direction is no reason to be brittle in
# the other. First key present wins; a record that yields no title, no employer
# or no text is skipped rather than stored half-built.
_TITLE_KEYS = ("stellenangebotsTitel", "titel", "hauptberuf", "beruf")
_EMPLOYER_KEYS = ("firma", "arbeitgeber")
_REFERENCE_KEYS = ("referenznummer", "refnr", "hashId")
_DATE_KEYS = (
    "datumErsteVeroeffentlichung",
    "aktuelleVeroeffentlichungsdatum",
    "ersteVeroeffentlichungsdatum",
)
_TEXT_KEYS = ("stellenangebotsBeschreibung", "stellenbeschreibung")
_PLACE_KEYS = ("stellenlokationen", "arbeitsorte", "arbeitsort")

# The key the agency's own app sends. Not a secret and not issued to anyone, so
# it belongs in the source rather than in .env - putting it in configuration
# would imply the reader has to obtain one, and they do not.
API_KEY = "jobboerse-jobsuche"

# Sent because the endpoint is the app's. Pretending to be a browser would be
# the dishonest choice; this says what is calling.
_USER_AGENT = "praxa/1.0 (personal project; https://github.com/Prathiba11/praxa)"

# Per request. Twenty seconds times forty requests is thirteen minutes of
# spinner, which is what "it runs forever" actually looks like.
_TIMEOUT = 8.0
_PAGE_SIZE = 10

#: Wall-clock ceiling for one fetch, in seconds.
#:
#: The call budget below bounds how many requests are made, not how long they
#: take. A slow or half-responsive endpoint satisfies every count-based limit
#: and still runs for minutes, and the Fetch button gives a person no way to
#: tell that from a hang. So the fetch also watches the clock and returns what
#: it has: a short list now beats a complete list nobody waited for.
_DEADLINE_SECONDS = 25.0

# How many detail lookups **one fetch** may spend in total, across every track
# and every search term. The search is one request and the details are one
# each, so without a ceiling here a full sync is nine searches times a page of
# results - roughly two hundred sequential HTTP calls, which is minutes of
# spinner. Counting per search term instead of per fetch is the mistake that
# produced exactly that, so the budget is shared and drains as it is used.
DETAIL_BUDGET = 30

# `angebotsart=1` is "Arbeit" - employment. Without it the results include
# training places and self-employment, which are not what any of these CVs want.
_OFFER_TYPE_EMPLOYMENT = "1"

# What to ask the Jobboerse for, per track. These are search terms, not the
# scoring vocabulary in `base.py`: the agency matches them against its own
# occupation taxonomy, so the German wording earns results the English does not.
TRACK_TERMS: dict[Profile, tuple[str, ...]] = {
    Profile.AUTOMOTIVE_CYBER: (
        "Automotive Cybersecurity",
        "Fahrzeugsicherheit Cybersecurity",
        "Security Engineer Automotive",
    ),
    Profile.DEVOPS: (
        "DevOps Engineer",
        "Site Reliability Engineer",
        "Kubernetes Cloud Engineer",
    ),
    Profile.AI_ENG: (
        "AI Engineer",
        "Machine Learning Engineer",
        "KI Entwickler",
    ),
}


def _readable(value: str) -> str:
    """BADEN_WUERTTEMBERG -> Baden Wuerttemberg. Anything else, untouched.

    The API shouts its enums and a card is read by a person, not a parser. But
    the reshaping only applies to a value that is actually shouted: run over an
    ordinary name, `capitalize()` lowercases the rest of it and turns
    "Baden-Wuerttemberg" into "Baden-wuerttemberg". So a value that is not
    all-uppercase is left exactly as it came.
    """
    cleaned = value.strip()
    if not cleaned or cleaned != cleaned.upper():
        return cleaned
    return " ".join(word.capitalize() for word in cleaned.replace("_", " ").split())


def _first(raw: dict[str, Any], keys: tuple[str, ...]) -> str:
    """The first of `keys` that holds a non-empty string, stripped, else ''.

    The API has renamed a field between versions at least once, so every read
    goes through here rather than naming one key and hoping.
    """
    for key in keys:
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


class ArbeitsagenturSource:
    """Searches per track, then fetches the text each result hides."""

    name = "arbeitsagentur"

    def __init__(self, client: httpx.Client | None = None) -> None:
        # Injected for tests, which drive it with httpx.MockTransport rather
        # than hitting the network.
        self._client = client

    # ------------------------------------------------------------------ api

    def fetch(
        self,
        *,
        limit: int = 50,
        keywords: tuple[str, ...] = (),
        location: str | None = "Stuttgart",
        radius_km: int = 50,
        profiles: tuple[Profile, ...] = (),
        published_within_days: int | None = None,
        max_seconds: float = _DEADLINE_SECONDS,
    ) -> list[JobPosting]:
        """Return up to `limit` postings, only for the tracks asked for.

        `keywords`, when given, replace the per-track terms - the tool layer
        passes a user's own words through this way. `profiles` narrows which
        tracks are searched; empty means all three.

        Raises:
            JobSourceError: the API was unreachable or returned nonsense.
        """
        client = self._client or build_client(_TIMEOUT)
        close_after = self._client is None
        collected: list[JobPosting] = []
        seen: set[str] = set()
        budget = DETAIL_BUDGET
        deadline = monotonic() + max_seconds

        try:
            for profile, terms in self._plan(profiles, keywords):
                for term in terms:
                    if len(collected) >= limit or budget <= 0:
                        return collected
                    if monotonic() >= deadline:
                        log.warning(
                            "arbeitsagentur fetch hit its deadline",
                            extra={"returned": len(collected), "seconds": max_seconds},
                        )
                        return collected
                    found, spent = self._search_one(
                        client,
                        term=term,
                        profile=profile,
                        location=location,
                        radius_km=radius_km,
                        published_within_days=published_within_days,
                        seen=seen,
                        room=limit - len(collected),
                        budget=budget,
                        deadline=deadline,
                    )
                    collected.extend(found)
                    budget -= spent
        finally:
            if close_after:
                client.close()

        log.info(
            "arbeitsagentur fetch complete",
            extra={
                "returned": len(collected),
                "considered": len(seen),
                "details_spent": DETAIL_BUDGET - budget,
            },
        )
        return collected[:limit]

    # ----------------------------------------------------------- planning

    @staticmethod
    def _plan(
        profiles: tuple[Profile, ...],
        keywords: tuple[str, ...],
    ) -> list[tuple[Profile | None, tuple[str, ...]]]:
        """Which searches to run, as (track, terms) pairs.

        Explicit keywords win and carry no track, so a free search is still
        classified on its own evidence rather than on the caller's intent.
        """
        if keywords:
            return [(None, keywords)]
        wanted = profiles or tuple(TRACK_TERMS)
        return [(profile, TRACK_TERMS[profile]) for profile in wanted if profile in TRACK_TERMS]

    # --------------------------------------------------------------- http

    @staticmethod
    def _headers() -> dict[str, str]:
        """Sent on every request rather than baked into a client we built.

        A caller can inject its own `httpx.Client` - the tests do - and the key
        has to survive that, otherwise the one header the endpoint requires is
        exactly the one nothing exercises.
        """
        return {"X-API-Key": API_KEY, "User-Agent": _USER_AGENT, "Accept": "application/json"}

    def _search_one(
        self,
        client: httpx.Client,
        *,
        term: str,
        profile: Profile | None,
        location: str | None,
        radius_km: int,
        published_within_days: int | None,
        seen: set[str],
        room: int,
        budget: int,
        deadline: float,
    ) -> tuple[list[JobPosting], int]:
        params: dict[str, str] = {
            "was": term,
            "page": "1",
            "size": str(_PAGE_SIZE),
            "angebotsart": _OFFER_TYPE_EMPLOYMENT,
        }
        if location:
            params["wo"] = location
            params["umkreis"] = str(radius_km)
        if published_within_days is not None:
            params["veroeffentlichtseit"] = str(max(0, min(100, published_within_days)))

        payload = self._get_json(client, SEARCH_URL, params=params, what=f"search {term!r}")
        offers = self._results(payload)

        out: list[JobPosting] = []
        spent = 0
        for raw in offers:
            # The clock is read here as well as between search terms. Checking
            # only between them let one search spend the entire detail budget
            # before the deadline was looked at again - a ceiling that a single
            # slow search walks straight through. A test caught it.
            if len(out) >= room or spent >= budget or monotonic() >= deadline:
                break
            if not isinstance(raw, dict):
                continue
            refnr = _first(raw, _REFERENCE_KEYS)
            if not refnr or refnr in seen:
                continue
            seen.add(refnr)

            # When the search result already carries the posting text, the
            # detail call is pure waste - and it is the expensive half.
            description = html_to_text(_first(raw, _TEXT_KEYS))
            if not description:
                description = self._detail_text(client, refnr)
                spent += 1

            posting = self._normalise(raw, refnr=refnr, description=description, track=profile)
            if posting is not None:
                out.append(posting)
        return out, spent

    @staticmethod
    def _results(payload: Any) -> list[Any]:
        """The result list, whatever this version of the API calls it."""
        if not isinstance(payload, dict):
            raise JobSourceError("arbeitsagentur returned something that was not an object")
        for key in _RESULT_KEYS:
            value = payload.get(key)
            if isinstance(value, list):
                return value
        raise JobSourceError(
            f"arbeitsagentur response had none of {_RESULT_KEYS} - it has {sorted(payload)}"
        )

    def _detail_text(self, client: httpx.Client, refnr: str) -> str:
        """The posting body, or '' when the detail call has nothing to give.

        A missing detail is not a failed fetch. One posting the agency has since
        withdrawn should not sink a whole sync, so this degrades to empty text
        and lets `_normalise` drop the posting for having nothing to score.
        """
        code = quote(base64.b64encode(refnr.encode("utf-8")).decode("ascii"), safe="")
        try:
            response = client.get(DETAIL_URL.format(code=code), headers=self._headers())
            if response.status_code == 404:
                return ""
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            log.warning(
                "arbeitsagentur detail unavailable",
                extra={"refnr": refnr, "error": f"{type(exc).__name__}: {exc}"},
            )
            return ""

        if not isinstance(payload, dict):
            return ""
        body = payload.get("stellenbeschreibung") or payload.get("stellenangebotsBeschreibung")
        return html_to_text(str(body or ""))

    def _get_json(
        self,
        client: httpx.Client,
        url: str,
        *,
        params: dict[str, str],
        what: str,
    ) -> Any:
        try:
            response = client.get(url, params=params, headers=self._headers())
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as exc:
            raise JobSourceError(
                f"arbeitsagentur {what} failed: {type(exc).__name__}: {exc}"
            ) from exc
        except ValueError as exc:
            raise JobSourceError(
                f"arbeitsagentur {what} returned a body that was not JSON"
            ) from exc

    # ---------------------------------------------------------- normalise

    def _normalise(
        self,
        raw: dict[str, Any],
        *,
        refnr: str,
        description: str,
        track: Profile | None,
    ) -> JobPosting | None:
        title = _first(raw, _TITLE_KEYS)
        company = _first(raw, _EMPLOYER_KEYS)
        if not title or not company or not description:
            # Logged rather than dropped in silence: if the API renames a field
            # again, this is the line that says so instead of an empty board.
            log.debug(
                "arbeitsagentur record incomplete",
                extra={
                    "refnr": refnr,
                    "has_title": bool(title),
                    "has_company": bool(company),
                    "has_text": bool(description),
                    "keys": sorted(raw),
                },
            )
            return None

        profile = classify_profile(title, description)
        if profile is None:
            # See the module docstring: a per-track search that returns
            # something unrecognisable has missed, and a miss is not a job.
            log.debug(
                "arbeitsagentur result did not classify",
                extra={"refnr": refnr, "title": title, "searched_for": track},
            )
            return None

        return JobPosting(
            source=self.name,
            title=title,
            company=company,
            description=description,
            location=self._place(raw),
            url=self._url(raw, refnr),
            posted_at=self._posted_at(_first(raw, _DATE_KEYS)),
            language=detect_language(f"{title}\n{description}"),
            profile=profile,
            tags=(),
        )

    @staticmethod
    def _place(raw: dict[str, Any]) -> str | None:
        """'Stuttgart, Baden Wuerttemberg' from whichever location shape arrived.

        v6 sends `stellenlokationen`, a list whose entries wrap the address one
        level down under `adresse`. Older shapes put the same fields directly on
        an `arbeitsort` object. Both are unwrapped here rather than in two
        places, and the region arrives as a shouted enum - BADEN_WUERTTEMBERG -
        which is tidied because it is going on a card a person reads.
        """
        for key in _PLACE_KEYS:
            value = raw.get(key)
            if isinstance(value, list):
                value = next((item for item in value if isinstance(item, dict)), None)
            if not isinstance(value, dict):
                continue
            # Bound once. Calling `.get` twice reads as one check but is two,
            # and the second call is what the type says it is: possibly None.
            nested = value.get("adresse")
            address = nested if isinstance(nested, dict) else value

            town = str(address.get("ort") or "").strip()
            region = _readable(str(address.get("region") or ""))
            parts: Iterable[str] = (part for part in (town, region) if part)
            joined = ", ".join(parts)
            if joined:
                return joined
        return None

    @staticmethod
    def _url(raw: dict[str, Any], refnr: str) -> str:
        """The employer's own link when there is one, else the Jobboerse page."""
        external = _first(raw, ("externeUrl",))
        if external:
            return external
        return f"https://www.arbeitsagentur.de/jobsuche/jobdetail/{quote(refnr, safe='')}"

    @staticmethod
    def _posted_at(value: Any) -> datetime | None:
        """An ISO date, midnight UTC. Anything unparseable is dropped rather
        than guessed at - a wrong date silently corrupts the 'new today' view."""
        if not isinstance(value, str) or not value.strip():
            return None
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
