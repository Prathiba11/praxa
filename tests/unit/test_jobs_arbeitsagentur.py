"""The Bundesagentur source, driven by scripted responses.

`httpx.MockTransport` runs the real request handling against a fake network, so
what these assert is the actual parsing and the actual two-call shape rather
than a reimplementation of it. The interesting cases are the ones the API forces
on us: the description living behind a second call, and that second call being
allowed to fail without taking the sync with it.
"""

from __future__ import annotations

import base64
from time import monotonic, sleep

import httpx
import pytest

from career_copilot.core.types import Profile
from career_copilot.jobs.arbeitsagentur import (
    API_KEY,
    DETAIL_BUDGET,
    TRACK_TERMS,
    ArbeitsagenturSource,
)
from career_copilot.jobs.base import JobSource, JobSourceError

_DEVOPS_BODY = (
    "<p>Sie betreuen unsere <b>Kubernetes</b> Cluster.</p>"
    "<ul><li>Terraform</li><li>GitLab CI</li><li>Prometheus</li></ul>"
    "<p>Site Reliability Engineering und Observability sind Ihr Thema.</p>"
)

# Copied from a real v6 response, not invented. The first version of this file
# used the field names the published spec gives - `arbeitgeber`, `arbeitsort`,
# `aktuelleVeroeffentlichungsdatum`, `refnr` - and every one of them is wrong:
# the live endpoint sends `firma`, `stellenlokationen`, `datumErsteVeroeffent-
# lichung` and `referenznummer`, and wraps the address one level deeper. A
# fixture that agrees with the documentation and disagrees with the server
# proves nothing, so this one agrees with the server.
_OFFER = {
    "stellenangebotsart": "ARBEIT",
    "stellenangebotsTitel": "DevOps Engineer Azure (m/w/d)",
    "hauptberuf": "DevOps Engineer",
    "firma": "FERCHAU GmbH Niederlassung Stuttgart Mobility",
    "referenznummer": "12265-351160_JB5253398-S",
    "datumErsteVeroeffentlichung": "2026-09-22",
    "aenderungsdatum": "2026-09-22T07:43:36.000",
    "stellenlokationen": [
        {
            "adresse": {
                "plz": "70629",
                "ort": "Stuttgart",
                "region": "BADEN_WUERTTEMBERG",
                "land": "DEUTSCHLAND",
            },
            "breite": 48.68888204,
            "laenge": 9.199591472,
        }
    ],
    "entfernung": 9,
    "arbeitgeberKundennummerHash": "ROik87b7c4puiQuhGetKx6ykdxR8Oqrk7zm8oH8gSdU=",
}

#: The shape the published spec describes. Kept so the fallback keys stay
#: exercised - the spec being wrong today is no guarantee it stays wrong.
_LEGACY_OFFER = {
    "refnr": "10000-1234567890-S",
    "titel": "DevOps Engineer (m/w/d)",
    "arbeitgeber": "Robert Bosch GmbH",
    "aktuelleVeroeffentlichungsdatum": "2026-09-01",
    "arbeitsort": {"ort": "Stuttgart", "region": "Baden-Wuerttemberg", "plz": "70173"},
}


def _detail_path(refnr: str) -> str:
    return base64.b64encode(refnr.encode("utf-8")).decode("ascii")


def _handler(offers, *, detail=_DEVOPS_BODY, detail_status=200, search_status=200):
    """One handler for both endpoints, routed on the path.

    Returns the handler and its call counter as a pair, rather than hanging the
    counter off the function, so nothing here needs a type suppression.
    """
    calls: dict[str, int] = {"search": 0, "detail": 0}

    def handle(request: httpx.Request) -> httpx.Response:
        if "jobdetails" in request.url.path:
            calls["detail"] += 1
            if detail_status != 200:
                return httpx.Response(detail_status, json={})
            return httpx.Response(200, json={"stellenangebotsBeschreibung": detail})
        calls["search"] += 1
        if search_status != 200:
            return httpx.Response(search_status, text="nope")
        return httpx.Response(200, json={"ergebnisliste": offers, "maxErgebnisse": len(offers)})

    return handle, calls


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


# ------------------------------------------------------------------ contract


def test_the_source_satisfies_the_protocol():
    assert isinstance(ArbeitsagenturSource(), JobSource)


def test_every_track_has_search_terms():
    """A track with no terms would be silently unsearchable."""
    for profile in (Profile.AUTOMOTIVE_CYBER, Profile.DEVOPS, Profile.AI_ENG):
        assert TRACK_TERMS[profile], f"{profile} has no search terms"


def test_general_is_not_searched():
    """The General shelf is a CV, not a kind of job to go looking for."""
    assert Profile.GENERAL not in TRACK_TERMS


# ------------------------------------------------------------------ fetching


def test_a_posting_is_normalised():
    handle, _ = _handler([_OFFER])
    source = ArbeitsagenturSource(client=_client(handle))
    postings = source.fetch(limit=1, profiles=(Profile.DEVOPS,))

    assert len(postings) == 1
    job = postings[0]
    assert job.source == "arbeitsagentur"
    assert job.title == "DevOps Engineer Azure (m/w/d)"
    assert job.company == "FERCHAU GmbH Niederlassung Stuttgart Mobility"
    assert job.location == "Stuttgart, Baden Wuerttemberg"
    assert job.profile is Profile.DEVOPS
    assert job.language == "de"
    assert "Kubernetes" in job.description
    assert "<b>" not in job.description
    assert job.posted_at is not None
    assert job.posted_at.year == 2026


def test_the_description_comes_from_a_second_call():
    """If this stops being true the postings arrive with nothing to score."""
    handle, calls = _handler([_OFFER])
    source = ArbeitsagenturSource(client=_client(handle))
    source.fetch(limit=1, profiles=(Profile.DEVOPS,))

    assert calls["search"] == 1
    assert calls["detail"] == 1


def test_the_detail_url_carries_the_base64_reference():
    seen: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        if "jobdetails" in request.url.path:
            seen.append(request.url.path.rsplit("/", 1)[-1])
            return httpx.Response(200, json={"stellenangebotsBeschreibung": _DEVOPS_BODY})
        return httpx.Response(200, json={"ergebnisliste": [_OFFER]})

    ArbeitsagenturSource(client=_client(handle)).fetch(limit=1, profiles=(Profile.DEVOPS,))
    assert seen == [_detail_path(str(_OFFER["referenznummer"]))]


def test_the_api_key_is_sent_on_every_request():
    """The endpoint refuses without it, so this is the header worth pinning."""
    seen: list[str | None] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("X-API-Key"))
        if "jobdetails" in request.url.path:
            return httpx.Response(200, json={"stellenangebotsBeschreibung": _DEVOPS_BODY})
        return httpx.Response(200, json={"ergebnisliste": [_OFFER]})

    ArbeitsagenturSource(client=_client(handle)).fetch(limit=1, profiles=(Profile.DEVOPS,))
    assert len(seen) == 2  # one search, one detail
    assert all(value == API_KEY for value in seen)


def test_only_the_tracks_asked_for_are_searched():
    """Her rule: the board holds three kinds of job and no others."""
    terms: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        if "jobdetails" in request.url.path:
            return httpx.Response(200, json={"stellenangebotsBeschreibung": _DEVOPS_BODY})
        terms.append(request.url.params.get("was", ""))
        return httpx.Response(200, json={"ergebnisliste": []})

    ArbeitsagenturSource(client=_client(handle)).fetch(limit=50, profiles=(Profile.DEVOPS,))
    assert terms == list(TRACK_TERMS[Profile.DEVOPS])


def test_explicit_keywords_replace_the_track_terms():
    terms: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        terms.append(request.url.params.get("was", ""))
        return httpx.Response(200, json={"ergebnisliste": []})

    ArbeitsagenturSource(client=_client(handle)).fetch(limit=5, keywords=("Werkstudent RAG",))
    assert terms == ["Werkstudent RAG"]


def test_a_posting_that_does_not_classify_is_dropped():
    """A per-track search that returns a bakery is a miss, not a job.

    The bakery needs a bakery *title* as well as a bakery body. An earlier
    version of this test swapped only the description and left the title
    reading "DevOps Engineer", and it failed - correctly. The title carries
    three times the weight of a body term in `classify_profile`, so a posting
    titled DevOps Engineer is a DevOps job whatever the body rambles about.
    That is the classifier working, not a hole in it.
    """
    bakery = dict(_OFFER, stellenangebotsTitel="Baecker (m/w/d)", hauptberuf="Baecker")
    handle, _ = _handler([bakery], detail="<p>Wir backen Broetchen seit 1904.</p>")
    postings = ArbeitsagenturSource(client=_client(handle)).fetch(
        limit=5, profiles=(Profile.DEVOPS,)
    )
    assert postings == []


def test_a_posting_with_no_detail_text_is_dropped():
    handle, _ = _handler([_OFFER], detail_status=404)
    postings = ArbeitsagenturSource(client=_client(handle)).fetch(
        limit=5, profiles=(Profile.DEVOPS,)
    )
    assert postings == []


def test_a_failing_detail_call_does_not_sink_the_fetch():
    """One withdrawn posting must not cost the whole sync."""
    good = dict(_OFFER, referenznummer="10000-999-S")

    def handle(request: httpx.Request) -> httpx.Response:
        if "jobdetails" in request.url.path:
            if request.url.path.endswith(_detail_path(str(_OFFER["referenznummer"]))):
                return httpx.Response(500, text="boom")
            return httpx.Response(200, json={"stellenangebotsBeschreibung": _DEVOPS_BODY})
        return httpx.Response(200, json={"ergebnisliste": [_OFFER, good]})

    postings = ArbeitsagenturSource(client=_client(handle)).fetch(
        limit=5, profiles=(Profile.DEVOPS,)
    )
    assert [job.url for job in postings] == [
        "https://www.arbeitsagentur.de/jobsuche/jobdetail/10000-999-S"
    ]


def test_the_same_posting_is_not_returned_twice():
    """Three search terms per track overlap; the reference number settles it."""
    handle, calls = _handler([_OFFER])
    postings = ArbeitsagenturSource(client=_client(handle)).fetch(
        limit=50, profiles=(Profile.DEVOPS,)
    )
    assert len(postings) == 1
    assert calls["search"] == len(TRACK_TERMS[Profile.DEVOPS])
    assert calls["detail"] == 1


def test_the_limit_is_respected():
    offers = [dict(_OFFER, referenznummer=f"10000-{n}-S") for n in range(10)]
    handle, _ = _handler(offers)
    postings = ArbeitsagenturSource(client=_client(handle)).fetch(
        limit=3, profiles=(Profile.DEVOPS,)
    )
    assert len(postings) == 3


def test_an_employer_link_wins_over_the_jobboerse_page():
    offer = dict(_OFFER, externeUrl="https://jobs.bosch.com/de/12345")
    handle, _ = _handler([offer])
    postings = ArbeitsagenturSource(client=_client(handle)).fetch(
        limit=1, profiles=(Profile.DEVOPS,)
    )
    assert postings[0].url == "https://jobs.bosch.com/de/12345"


def test_a_bad_date_is_dropped_not_guessed():
    offer = dict(_OFFER, datumErsteVeroeffentlichung="irgendwann", aenderungsdatum="")
    handle, _ = _handler([offer])
    postings = ArbeitsagenturSource(client=_client(handle)).fetch(
        limit=1, profiles=(Profile.DEVOPS,)
    )
    assert postings[0].posted_at is None


# -------------------------------------------------------------------- errors


def test_a_failed_search_raises():
    handle, _ = _handler([], search_status=503)
    source = ArbeitsagenturSource(client=_client(handle))
    with pytest.raises(JobSourceError, match="arbeitsagentur"):
        source.fetch(limit=1, profiles=(Profile.DEVOPS,))


def test_a_response_without_the_expected_list_raises():
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": "shape"})

    with pytest.raises(JobSourceError, match="ergebnisliste"):
        ArbeitsagenturSource(client=_client(handle)).fetch(limit=1, profiles=(Profile.DEVOPS,))


def test_the_detail_budget_is_shared_across_every_search():
    """Regression: the budget was per search term, so a sync spent nine times it.

    Nine searches over a page of results each is roughly two hundred sequential
    HTTP calls, which is what turned one click of Fetch jobs into minutes of
    spinner. The ceiling has to be a property of the fetch, not of one term.
    """
    offers = [dict(_OFFER, referenznummer=f"10000-{n}-S") for n in range(50)]
    handle, calls = _handler(offers)
    ArbeitsagenturSource(client=_client(handle)).fetch(limit=500)

    assert calls["detail"] <= DETAIL_BUDGET
    # And it really did stop early rather than never getting going.
    assert calls["detail"] == DETAIL_BUDGET


def test_the_documented_field_names_still_parse():
    """The spec's names are fallbacks, and a fallback nothing exercises is a lie.

    If the endpoint ever moves back to the documented shape - or a fourth
    version splits the difference - this is what says the reader survives it.
    """
    handle, _ = _handler([_LEGACY_OFFER])
    postings = ArbeitsagenturSource(client=_client(handle)).fetch(
        limit=1, profiles=(Profile.DEVOPS,)
    )

    assert len(postings) == 1
    job = postings[0]
    assert job.title == "DevOps Engineer (m/w/d)"
    assert job.company == "Robert Bosch GmbH"
    assert job.location == "Stuttgart, Baden-Wuerttemberg"


def test_the_shouted_region_enum_is_tidied():
    """BADEN_WUERTTEMBERG goes on a card a person reads, not into a parser."""
    handle, _ = _handler([_OFFER])
    postings = ArbeitsagenturSource(client=_client(handle)).fetch(
        limit=1, profiles=(Profile.DEVOPS,)
    )
    assert postings[0].location == "Stuttgart, Baden Wuerttemberg"


def test_a_search_result_carrying_its_own_text_skips_the_detail_call():
    """The detail call is the expensive half; it is not spent when it is not needed."""
    inline = dict(_OFFER, stellenangebotsBeschreibung=_DEVOPS_BODY)
    handle, calls = _handler([inline])
    postings = ArbeitsagenturSource(client=_client(handle)).fetch(
        limit=1, profiles=(Profile.DEVOPS,)
    )

    assert len(postings) == 1
    assert calls["detail"] == 0


def test_the_fetch_stops_at_its_deadline():
    """A call budget bounds how many requests are made, not how long they take.

    A half-responsive endpoint satisfies every count-based limit and still runs
    for minutes, which from the Fetch button is indistinguishable from a hang.
    """
    offers = [dict(_OFFER, referenznummer=f"10000-{n}-S") for n in range(50)]
    handle, calls = _handler(offers)

    # Every request costs a tenth of a second of pretend network time.
    def slow(request: httpx.Request) -> httpx.Response:
        sleep(0.1)
        return handle(request)

    started = monotonic()
    postings = ArbeitsagenturSource(client=_client(slow)).fetch(limit=500, max_seconds=0.3)
    elapsed = monotonic() - started

    # It stopped early rather than spending the whole call budget.
    assert calls["detail"] < DETAIL_BUDGET
    assert elapsed < 3.0
    # And it returned what it had rather than throwing it away.
    assert postings


def test_hitting_the_deadline_is_not_an_error():
    """A short list now beats a complete list nobody waited for."""
    offers = [dict(_OFFER, referenznummer=f"10000-{n}-S") for n in range(50)]
    handle, _ = _handler(offers)

    postings = ArbeitsagenturSource(client=_client(handle)).fetch(limit=500, max_seconds=0.0)
    assert postings == []
