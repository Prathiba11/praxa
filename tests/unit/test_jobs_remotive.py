"""The Remotive source, and the registry that picks between sources."""

from __future__ import annotations

import httpx
import pytest

from career_copilot.core.types import Profile
from career_copilot.jobs import SOURCES, get_source
from career_copilot.jobs.base import JobSource, JobSourceError
from career_copilot.jobs.remotive import RemotiveSource

_JOB = {
    "id": 1,
    "url": "https://remotive.com/remote-jobs/devops/platform-engineer-1",
    "title": "Senior Platform Engineer",
    "company_name": "Example Cloud",
    "category": "DevOps / Sysadmin",
    "tags": ["kubernetes", "terraform"],
    "job_type": "full_time",
    "publication_date": "2026-08-20T09:30:00",
    "candidate_required_location": "Europe",
    "description": "<p>Run <b>Kubernetes</b> clusters and write Terraform modules.</p>",
}


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _responds(jobs, status=200):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"job-count": len(jobs), "jobs": jobs})

    return handler


# ------------------------------------------------------------------ registry


def test_both_sources_are_registered():
    assert {"arbeitnow", "remotive"} <= set(SOURCES)


@pytest.mark.parametrize("name", ["arbeitnow", "remotive"])
def test_every_registered_source_satisfies_the_protocol(name):
    assert isinstance(get_source(name), JobSource)


def test_an_unknown_source_is_a_typed_error():
    with pytest.raises(JobSourceError) as excinfo:
        get_source("linkedin")
    assert "available" in str(excinfo.value.detail)


# ------------------------------------------------------------------ fetching


def test_a_posting_is_normalised():
    postings = RemotiveSource(client=_client(_responds([_JOB]))).fetch(limit=1)

    assert len(postings) == 1
    job = postings[0]
    assert job.source == "remotive"
    assert job.company == "Example Cloud"
    assert job.location == "Europe"
    assert job.profile == Profile.DEVOPS
    assert "<b>" not in job.description


def test_the_category_joins_the_tags_so_it_can_inform_classification():
    postings = RemotiveSource(client=_client(_responds([_JOB]))).fetch(limit=1)
    assert "DevOps / Sysadmin" in postings[0].tags


def test_keywords_are_sent_to_the_api_as_one_search_term():
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.url.params))
        return httpx.Response(200, json={"jobs": [_JOB]})

    RemotiveSource(client=_client(handler)).fetch(keywords=("kubernetes", "terraform"))
    assert seen["search"] == "kubernetes terraform"


def test_the_iso_publication_date_becomes_aware_utc():
    posted = RemotiveSource(client=_client(_responds([_JOB]))).fetch(limit=1)[0].posted_at
    assert posted is not None
    assert posted.tzinfo is not None
    assert posted.year == 2026


def test_an_unparseable_date_is_dropped_rather_than_guessed():
    broken = {**_JOB, "publication_date": "last Tuesday"}
    assert RemotiveSource(client=_client(_responds([broken]))).fetch(limit=1)[0].posted_at is None


def test_location_filtering_is_applied_client_side():
    source = RemotiveSource(client=_client(_responds([_JOB])))
    assert source.fetch(location="europe")
    assert not source.fetch(location="Stuttgart")


def test_the_limit_is_respected():
    jobs = [{**_JOB, "title": f"Engineer {i}"} for i in range(20)]
    assert len(RemotiveSource(client=_client(_responds(jobs))).fetch(limit=4)) == 4


def test_postings_without_a_company_are_skipped():
    source = RemotiveSource(client=_client(_responds([{**_JOB, "company_name": ""}])))
    assert source.fetch() == []


# ------------------------------------------------------------------ failures


def test_a_server_error_is_a_typed_error():
    def handler(_request):
        return httpx.Response(502, text="bad gateway")

    with pytest.raises(JobSourceError):
        RemotiveSource(client=_client(handler)).fetch()


def test_a_missing_jobs_key_is_a_typed_error():
    def handler(_request):
        return httpx.Response(200, json={"job-count": 0})

    with pytest.raises(JobSourceError) as excinfo:
        RemotiveSource(client=_client(handler)).fetch()
    assert "jobs" in str(excinfo.value.detail)
