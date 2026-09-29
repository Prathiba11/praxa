"""Fetching through to stored rows, against a real database.

The unit tests prove a source normalises correctly. This proves the normalised
result survives the trip into SQLite, that a second sync does not duplicate
anything, and that the fields the tools read are actually populated.
"""

from __future__ import annotations

import httpx
import pytest

from career_copilot.core.types import ApplicationStatus, Profile
from career_copilot.jobs import paste
from career_copilot.jobs.arbeitnow import ArbeitnowSource
from career_copilot.jobs.sync import save_posting, sync_source
from career_copilot.storage import jobs as repo

pytestmark = pytest.mark.slow

_JOBS = [
    {
        "company_name": "Robert Bosch GmbH",
        "title": "Platform Engineer (m/w/d)",
        "description": "<p>Kubernetes, Terraform and GitLab CI.</p>",
        "location": "Stuttgart",
        "url": "https://example.com/1",
        "tags": ["devops"],
        "created_at": 1735689600,
        "remote": False,
    },
    {
        "company_name": "Continental AG",
        "title": "Automotive Security Engineer",
        "description": "<p>TARA per ISO/SAE 21434 and UNECE R155 work.</p>",
        "location": "Regensburg",
        "url": "https://example.com/2",
        "tags": ["security"],
        "created_at": 1735689600,
        "remote": False,
    },
]


def _source(jobs=None) -> ArbeitnowSource:
    payload = _JOBS if jobs is None else jobs

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": payload})

    return ArbeitnowSource(client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_a_sync_stores_every_posting(isolated_settings):
    report = sync_source(_source(), limit=10, pages=1)

    assert report.fetched == 2
    assert report.added == 2
    assert repo.count_jobs() == 2


def test_syncing_twice_adds_nothing(isolated_settings):
    sync_source(_source(), limit=10, pages=1)
    second = sync_source(_source(), limit=10, pages=1)

    assert second.added == 0
    assert second.updated == 2
    assert repo.count_jobs() == 2


def test_the_classified_profile_reaches_the_database(isolated_settings):
    sync_source(_source(), limit=10, pages=1)
    assert len(repo.search_jobs(profile=Profile.DEVOPS)) == 1
    assert len(repo.search_jobs(profile=Profile.AUTOMOTIVE_CYBER)) == 1


def test_html_never_reaches_the_stored_description(isolated_settings):
    """Markup in the description would end up embedded, retrieved and shown."""
    sync_source(_source(), limit=10, pages=1)
    for job in repo.search_jobs():
        assert "<p>" not in job.description


def test_unclassified_postings_are_counted_not_hidden(isolated_settings):
    vague = [{**_JOBS[0], "title": "Engineer", "description": "<p>You will write code.</p>"}]
    report = sync_source(_source(vague), limit=10, pages=1)

    assert report.unclassified == 1
    assert repo.count_jobs() == 1
    assert repo.search_jobs(profile=Profile.DEVOPS) == []


def test_a_pasted_posting_lands_beside_fetched_ones(isolated_settings):
    sync_source(_source(), limit=10, pages=1)
    job_id = save_posting(
        paste.from_text(
            "Kubernetes, Terraform and ArgoCD platform work in Stuttgart. " * 4,
            title="Senior Platform Engineer",
            company="Beispiel GmbH",
        )
    )

    assert repo.count_jobs() == 3
    stored = repo.get_job(job_id)
    assert stored is not None
    assert stored.source == "pasted"


def test_a_pasted_duplicate_of_a_fetched_job_merges(isolated_settings):
    """The same role from two routes is one row - that is what the fingerprint
    is for, and it is the case most likely to break it."""
    sync_source(_source(), limit=10, pages=1)
    save_posting(
        paste.from_text(
            "Kubernetes, Terraform and GitLab CI in Stuttgart. " * 5,
            title="Platform Engineer",
            company="Robert Bosch",
            location="Stuttgart",
        )
    )
    assert repo.count_jobs() == 2


def test_stored_jobs_are_ready_for_the_funnel(isolated_settings):
    sync_source(_source(), limit=10, pages=1)
    job = repo.search_jobs(profile=Profile.DEVOPS)[0]

    repo.set_application_status(job.id, ApplicationStatus.APPLIED)
    assert repo.funnel_counts()["applied"] == 1
    assert [j.id for j in repo.search_jobs(status=ApplicationStatus.APPLIED)] == [job.id]
