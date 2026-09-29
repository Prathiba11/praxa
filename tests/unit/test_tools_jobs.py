"""The job tools end-to-end against a throwaway database - no network."""

from __future__ import annotations

import pytest

from career_copilot.core.errors import ToolError
from career_copilot.core.types import ApplicationStatus, Profile
from career_copilot.storage import db as db_module
from career_copilot.storage import jobs as repo
from career_copilot.tools.job_search import search_jobs, set_application_status


class _FakeSettings:
    def __init__(self, db_path):
        self.db_path = db_path


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    db_module.reset_engine()
    monkeypatch.setattr(db_module, "get_settings", lambda: _FakeSettings(tmp_path / "t.db"))
    db_module.init_db()
    yield
    db_module.reset_engine()


@pytest.fixture()
def seeded(temp_db):
    devops = repo.upsert_job(
        source="test",
        title="DevOps Engineer",
        company="Bosch",
        location="Stuttgart",
        description="Kubernetes, Terraform, GitLab CI, Prometheus.",
        profile=Profile.DEVOPS,
    )
    cyber = repo.upsert_job(
        source="test",
        title="Automotive Security Engineer",
        company="Continental",
        location="Regensburg",
        description="ISO/SAE 21434, UNECE R155, TARA.",
        profile=Profile.AUTOMOTIVE_CYBER,
    )
    return devops, cyber


def test_search_returns_ids_the_other_tools_can_use(seeded):
    devops, _ = seeded
    output = search_jobs.run({"profile": "devops"})
    assert f"id={devops.id}" in output
    assert "Continental" not in output


def test_search_reports_an_empty_result_plainly(seeded):
    assert "No stored jobs match" in search_jobs.run({"company": "Nowhere Ltd"})


def test_search_keyword_filter_reaches_the_description(seeded):
    assert "Continental" in search_jobs.run({"keywords": ["TARA"]})


def test_search_rejects_an_invalid_profile_before_touching_the_database(seeded):
    with pytest.raises(ToolError):
        search_jobs.run({"profile": "quantum_alchemy"})


def test_search_rejects_an_oversized_limit(seeded):
    with pytest.raises(ToolError):
        search_jobs.run({"limit": 500})


def test_status_tool_moves_the_funnel(seeded):
    devops, _ = seeded
    output = set_application_status.run({"job_id": devops.id, "status": "applied"})
    assert "applied" in output
    assert repo.funnel_counts()["applied"] == 1


def test_status_tool_rejects_an_unknown_status(seeded):
    devops, _ = seeded
    with pytest.raises(ToolError):
        set_application_status.run({"job_id": devops.id, "status": "ghosted"})


def test_search_shows_status_once_it_is_set(seeded):
    devops, _ = seeded
    set_application_status.run({"job_id": devops.id, "status": "interview"})
    assert "status=interview" in search_jobs.run({"profile": "devops"})


def test_search_by_status_filters(seeded):
    devops, _ = seeded
    set_application_status.run({"job_id": devops.id, "status": ApplicationStatus.APPLIED})
    output = search_jobs.run({"status": "applied"})
    assert "Bosch" in output
    assert "Continental" not in output
