"""The Arbeitnow source and the paste path, without touching the network.

`httpx.MockTransport` lets the real client code run against scripted responses,
so what is tested is the actual request handling and parsing rather than a
reimplementation of it.
"""

from __future__ import annotations

import inspect
from types import SimpleNamespace

import httpx
import pytest

from career_copilot.core.errors import ValidationError
from career_copilot.core.types import Profile
from career_copilot.jobs import paste
from career_copilot.jobs.arbeitnow import ArbeitnowSource
from career_copilot.jobs.base import JobSource, JobSourceError

_JOB = {
    "slug": "platform-engineer-bosch",
    "company_name": "Robert Bosch GmbH",
    "title": "Platform Engineer (m/w/d)",
    "description": "<p>You will run <b>Kubernetes</b> clusters.</p><ul><li>Terraform</li></ul>",
    "remote": False,
    "url": "https://www.arbeitnow.com/jobs/platform-engineer-bosch",
    "tags": ["devops", "kubernetes"],
    "job_types": ["full_time"],
    "location": "Stuttgart",
    "created_at": 1735689600,
}


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _responds(jobs, status=200):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"data": jobs, "links": {}, "meta": {}})

    return handler


# ------------------------------------------------------------------ contract


def test_the_source_satisfies_the_protocol():
    assert isinstance(ArbeitnowSource(), JobSource)


# ------------------------------------------------------------------ fetching


def test_a_posting_is_normalised():
    source = ArbeitnowSource(client=_client(_responds([_JOB])))
    postings = source.fetch(limit=1, pages=1)

    assert len(postings) == 1
    job = postings[0]
    assert job.source == "arbeitnow"
    assert job.title == "Platform Engineer (m/w/d)"
    assert job.company == "Robert Bosch GmbH"
    assert job.location == "Stuttgart"
    assert job.profile == Profile.DEVOPS
    assert "<p>" not in job.description
    assert "Kubernetes" in job.description


def test_the_posted_date_is_timezone_aware():
    source = ArbeitnowSource(client=_client(_responds([_JOB])))
    posted = source.fetch(limit=1, pages=1)[0].posted_at
    assert posted is not None
    assert posted.tzinfo is not None


def test_a_nonsense_timestamp_is_dropped_rather_than_guessed():
    """A wrong date silently corrupts the 'new today' view."""
    source = ArbeitnowSource(client=_client(_responds([{**_JOB, "created_at": "yesterday"}])))
    assert source.fetch(limit=1, pages=1)[0].posted_at is None


def test_postings_without_a_company_are_skipped():
    """No company means no stable fingerprint, so it cannot be deduplicated."""
    source = ArbeitnowSource(client=_client(_responds([{**_JOB, "company_name": ""}])))
    assert source.fetch(limit=5, pages=1) == []


def test_the_limit_is_respected():
    jobs = [{**_JOB, "title": f"Engineer {i}"} for i in range(10)]
    source = ArbeitnowSource(client=_client(_responds(jobs)))
    assert len(source.fetch(limit=3, pages=1)) == 3


def test_keyword_filtering_matches_title_body_or_tags():
    source = ArbeitnowSource(client=_client(_responds([_JOB])))
    assert source.fetch(limit=5, pages=1, keywords=("terraform",))
    assert not source.fetch(limit=5, pages=1, keywords=("rust",))


def test_location_filtering_is_case_insensitive():
    source = ArbeitnowSource(client=_client(_responds([_JOB])))
    assert source.fetch(limit=5, pages=1, location="stuttg")
    assert not source.fetch(limit=5, pages=1, location="Berlin")


def test_remote_only_excludes_onsite_roles():
    source = ArbeitnowSource(client=_client(_responds([_JOB])))
    assert not source.fetch(limit=5, pages=1, remote_only=True)
    source = ArbeitnowSource(client=_client(_responds([{**_JOB, "remote": True}])))
    assert source.fetch(limit=5, pages=1, remote_only=True)


# ------------------------------------------------------------------ failures


def test_a_server_error_is_a_typed_error():
    def handler(_request):
        return httpx.Response(503, text="upstream down")

    with pytest.raises(JobSourceError):
        ArbeitnowSource(client=_client(handler)).fetch(pages=1)


def test_a_non_json_body_is_a_typed_error():
    def handler(_request):
        return httpx.Response(200, text="<html>maintenance</html>")

    with pytest.raises(JobSourceError):
        ArbeitnowSource(client=_client(handler)).fetch(pages=1)


def test_a_missing_data_key_is_a_typed_error():
    def handler(_request):
        return httpx.Response(200, json={"unexpected": "shape"})

    with pytest.raises(JobSourceError) as excinfo:
        ArbeitnowSource(client=_client(handler)).fetch(pages=1)
    assert "data" in str(excinfo.value.detail)


def test_a_connection_failure_is_a_typed_error():
    def handler(request):
        raise httpx.ConnectError("no route to host", request=request)

    with pytest.raises(JobSourceError):
        ArbeitnowSource(client=_client(handler)).fetch(pages=1)


# ------------------------------------------------------------------ paste: url


@pytest.mark.parametrize(
    "url",
    [
        "https://www.linkedin.com/jobs/view/123",
        "https://linkedin.com/jobs/view/123",
        "https://www.xing.com/jobs/456",
        "https://de.indeed.com/viewjob?jk=789",
        "https://www.stepstone.de/stellenangebote--x",
    ],
)
def test_sites_that_forbid_automation_are_refused_by_name(url):
    """Not a limitation - a decision. The message tells the user what to do
    instead, which keeps a person in the loop where the terms require one."""
    with pytest.raises(ValidationError) as excinfo:
        paste.from_url(url)
    assert "paste" in str(excinfo.value.detail).lower()


def test_a_permitted_page_is_fetched_and_parsed():
    html = (
        "<html><head><title>Platform Engineer - Beispiel GmbH</title></head>"
        "<body><p>" + ("We need Kubernetes and Terraform experience. " * 8) + "</p></body></html>"
    )

    def handler(_request):
        return httpx.Response(200, text=html)

    posting = paste.from_url("https://careers.example.com/jobs/1", client=_client(handler))
    assert posting.title == "Platform Engineer"
    assert posting.company == "Beispiel GmbH"
    assert posting.source == "pasted"
    assert posting.profile == Profile.DEVOPS


def test_a_javascript_rendered_page_says_so_instead_of_storing_nothing():
    def handler(_request):
        return httpx.Response(200, text="<html><body><div id='root'></div></body></html>")

    with pytest.raises(JobSourceError) as excinfo:
        paste.from_url("https://careers.example.com/jobs/1", client=_client(handler))
    assert "paste" in str(excinfo.value.detail).lower()


def test_a_fetch_failure_is_a_typed_error():
    def handler(_request):
        return httpx.Response(404)

    with pytest.raises(JobSourceError):
        paste.from_url("https://careers.example.com/gone", client=_client(handler))


# ------------------------------------------------------------------ paste: text


def test_pasted_text_becomes_a_posting():
    body = "Wir suchen eine DevOps Engineer mit Kubernetes und Terraform Erfahrung. " * 4
    posting = paste.from_text(body, title="DevOps Engineer", company="Beispiel GmbH")

    assert posting.company == "Beispiel GmbH"
    assert posting.profile == Profile.DEVOPS
    assert posting.language == "de"


def test_missing_title_and_company_get_placeholders_not_guesses():
    """An invented company name changes the fingerprint and splits one job in two."""
    posting = paste.from_text("Kubernetes and Terraform work. " * 10)
    assert posting.company == "Unknown company"
    assert posting.title == "Untitled role"


def test_a_snippet_too_short_to_score_is_refused():
    with pytest.raises(ValidationError) as excinfo:
        paste.from_text("DevOps Engineer wanted")
    assert "whole posting" in str(excinfo.value.detail)


# ------------------------------------------------- which filters reach a source


def test_a_source_is_only_sent_filters_it_accepts():
    """Regression: the sync route sent every filter to every source.

    `remote_only` means something to Arbeitnow and nothing to Remotive or the
    Bundesagentur, and an unexpected keyword raises `TypeError` - which is not a
    `CopilotError`, so it escaped the per-source error handling and took the
    whole sync request down instead of the one board.
    """
    from career_copilot.jobs.arbeitsagentur import ArbeitsagenturSource
    from career_copilot.jobs.remotive import RemotiveSource
    from career_copilot.jobs.sync import fetch_kwargs_for

    requested: dict[str, object] = {
        "limit": 10,
        "keywords": ("kubernetes",),
        "location": "Stuttgart",
        "remote_only": True,
        "pages": 2,
    }

    assert fetch_kwargs_for(ArbeitnowSource(), **requested) == requested
    assert "remote_only" not in fetch_kwargs_for(RemotiveSource(), **requested)
    assert "pages" not in fetch_kwargs_for(RemotiveSource(), **requested)
    assert "remote_only" not in fetch_kwargs_for(ArbeitsagenturSource(), **requested)


def test_every_registered_source_survives_the_full_filter_set():
    """The property the route depends on, checked over the registry itself.

    A fourth source added without a thought for this cannot pass here.
    """
    from career_copilot.jobs import SOURCES
    from career_copilot.jobs.sync import fetch_kwargs_for

    requested: dict[str, object] = {
        "limit": 1,
        "keywords": (),
        "location": None,
        "remote_only": False,
        "pages": 1,
    }
    for name, factory in SOURCES.items():
        source = factory()
        accepted = fetch_kwargs_for(source, **requested)
        signature = inspect.signature(source.fetch)
        assert set(accepted) <= set(signature.parameters), name
        signature.bind(**accepted)  # raises TypeError if the route would break


# ------------------------------------------------------- connection settings


def test_the_client_honours_the_ipv4_setting(monkeypatch):
    """Regression: 63 seconds per source, on a machine with no IPv6 route.

    `CC_FORCE_IPV4` already existed for the model client, where this same
    problem was found. The job sources each built a bare `httpx.Client` and so
    never saw it. Arbeitnow and Remotive sit behind Cloudflare and publish IPv6
    addresses; Python tries the resolved addresses in order and waits out a TCP
    timeout on each before reaching IPv4. Measured: 63.7s, and 0.3s once forced.

    The transport argument is captured rather than read back off the built
    client, because reading it back means reaching into httpx's internals and
    this should not break the day they rename a private attribute.
    """
    from career_copilot.jobs import base

    captured: list[str | None] = []
    real_transport = httpx.HTTPTransport

    def spy(**kwargs):
        captured.append(kwargs.get("local_address"))
        return real_transport(**kwargs)

    monkeypatch.setattr(base.httpx, "HTTPTransport", spy)

    for force, expected in ((True, "0.0.0.0"), (False, None)):
        monkeypatch.setattr(
            base, "get_settings", lambda force=force: SimpleNamespace(force_ipv4=force)
        )
        with base.build_client(5.0):
            pass
        assert captured[-1] == expected, f"force_ipv4={force} should bind {expected!r}"


def test_no_source_builds_its_own_bare_client():
    """The property that keeps the fix from being undone one source at a time.

    A source that constructs `httpx.Client(...)` directly silently opts out of
    every connection setting. `build_client` is the only place allowed to.
    """
    from pathlib import Path

    package = Path(__import__("career_copilot").__file__).parent / "jobs"
    offenders = [
        path.name
        for path in sorted(package.glob("*.py"))
        if path.name != "base.py" and "httpx.Client(" in path.read_text(encoding="utf-8")
    ]
    assert offenders == [], f"these build their own client instead of build_client: {offenders}"
