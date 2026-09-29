"""Scoring a posting from the Jobs page.

The endpoint exists so the page can show a match without sending the user to the
chat. It is the one route on that router that costs money and takes seconds, so
the tests below are mostly about the cases where it must *not* run: an unknown
posting, and one the classifier could not place.

That second case matters more than it looks. A posting with no profile has no CV
to score against, and picking one would produce a confident percentage with
nothing behind it - the exact failure this project's evaluation section spends
its length arguing against. It refuses instead.
"""

from __future__ import annotations

import pytest

from career_copilot.api.routes import jobs as jobs_route
from career_copilot.core.errors import ToolError
from career_copilot.core.types import Profile
from career_copilot.storage import jobs as repo
from career_copilot.storage.db import init_db
from career_copilot.tools.fit import FitReport

_REPORT = FitReport(
    score=0.82,
    matched=["Kubernetes - operated clusters at Bosch"],
    missing=["Terraform"],
    blockers=[],
    conflicts=["will not take roles with on-call - posting requires a weekly rota"],
    verdict="Strong on evidence, but it carries on-call, which you have ruled out.",
)


@pytest.fixture()
def stub_score(monkeypatch):
    """Replace the model call. What is under test is the route, not the prompt."""
    calls: list[tuple[Profile, str, str | None]] = []

    def _score(profile, job_text, *, job_id=None):
        calls.append((profile, job_text, job_id))
        return _REPORT

    monkeypatch.setattr(jobs_route, "score_posting", _score)
    return calls


def _job(profile: Profile | None = Profile.DEVOPS):
    init_db()
    return repo.upsert_job(
        source="test",
        title="Platform Engineer",
        company="Bosch",
        location="Stuttgart",
        description="Kubernetes, Terraform, and a weekly on-call rota.",
        profile=profile,
    )


def test_scoring_returns_every_list_the_agent_would_see(client, api_settings, stub_score):
    job = _job()

    body = client.post(f"/api/jobs/{job.id}/score").json()

    assert body["score"] == pytest.approx(0.82)
    assert body["profile"] == "devops"
    assert body["conflicts"] == [
        "will not take roles with on-call - posting requires a weekly rota"
    ]
    assert body["matched"] and body["missing"] and body["verdict"]


def test_the_posting_text_is_what_gets_scored(client, api_settings, stub_score):
    """Not the title, and not a summary - the stored description."""
    job = _job()

    client.post(f"/api/jobs/{job.id}/score")

    profile, text, job_id = stub_score[0]
    assert profile is Profile.DEVOPS
    assert "weekly on-call rota" in text
    assert job_id == job.id


def test_an_unclassified_posting_is_refused_rather_than_guessed(client, api_settings, stub_score):
    """No profile means no CV. A number here would be confident and baseless."""
    job = _job(profile=None)

    response = client.post(f"/api/jobs/{job.id}/score")

    assert response.status_code == 409
    assert stub_score == [], "the model must not be called for an unplaceable posting"


def test_an_unknown_posting_is_a_404(client, api_settings, stub_score):
    assert client.post("/api/jobs/does-not-exist/score").status_code == 404
    assert stub_score == []


def test_a_failing_scorer_surfaces_as_502_not_500(client, api_settings, monkeypatch):
    """The model is upstream. A failure there is not the application crashing."""

    def _boom(*_args, **_kwargs):
        raise ToolError("score_job_fit: model did not return a numeric score")

    monkeypatch.setattr(jobs_route, "score_posting", _boom)

    assert client.post(f"/api/jobs/{_job().id}/score").status_code == 502
