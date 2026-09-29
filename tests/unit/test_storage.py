"""Storage layer: fingerprinting, dedupe, filtering, the funnel.

Every test runs against a throwaway SQLite file in tmp_path. The engine and the
session factory are lru_cached, so both caches are cleared around each test -
otherwise the second test in a run would silently reuse the first one's database.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from career_copilot.core.types import ApplicationStatus, Profile
from career_copilot.storage import db as db_module
from career_copilot.storage import jobs as repo
from career_copilot.storage.models import Job, job_fingerprint


class _FakeSettings:
    def __init__(self, db_path):
        self.db_path = db_path


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    """A fresh database per test, with the engine caches reset around it."""
    db_module.reset_engine()
    monkeypatch.setattr(db_module, "get_settings", lambda: _FakeSettings(tmp_path / "copilot.db"))
    db_module.init_db()
    yield
    db_module.reset_engine()


def _add(**overrides):
    payload = {
        "source": "test",
        "title": "DevOps Engineer",
        "company": "Bosch",
        "location": "Stuttgart",
        "description": "Kubernetes, Terraform, GitLab CI.",
        "profile": Profile.DEVOPS,
    }
    payload.update(overrides)
    return repo.upsert_job(**payload)


# ------------------------------------------------------------------ fingerprint


def test_fingerprint_ignores_legal_suffix_and_gender_tag():
    a = job_fingerprint("Robert Bosch GmbH", "DevOps Engineer (m/w/d)", "Stuttgart")
    b = job_fingerprint("Robert Bosch", "DevOps Engineer", "Stuttgart")
    assert a == b


def test_fingerprint_ignores_seniority_prefix():
    assert job_fingerprint("Bosch", "Senior DevOps Engineer", "Stuttgart") == job_fingerprint(
        "Bosch", "DevOps Engineer", "Stuttgart"
    )


def test_fingerprint_separates_different_locations():
    assert job_fingerprint("Bosch", "DevOps Engineer", "Stuttgart") != job_fingerprint(
        "Bosch", "DevOps Engineer", "Berlin"
    )


def test_fingerprint_is_stable():
    assert job_fingerprint("Bosch", "DevOps Engineer", "Stuttgart") == job_fingerprint(
        "Bosch", "DevOps Engineer", "Stuttgart"
    )


# ------------------------------------------------------------------ upsert


def test_same_role_from_two_boards_stores_once(temp_db):
    _add(source="board-a", company="Robert Bosch GmbH", title="Senior DevOps Engineer (m/w/d)")
    _add(source="board-b", company="Robert Bosch", title="DevOps Engineer")
    assert repo.count_jobs() == 1


def test_upsert_refreshes_fields_on_second_sighting(temp_db):
    first = _add(description="old text")
    second = _add(description="new text", url="https://example.com/job")
    assert first.id == second.id
    stored = repo.get_job(first.id)
    assert stored is not None
    assert stored.description == "new text"
    assert stored.url == "https://example.com/job"


def test_upsert_keeps_first_seen_at(temp_db):
    first = _add()
    original = first.first_seen_at
    _add(description="updated")
    stored = repo.get_job(first.id)
    assert stored is not None
    assert stored.first_seen_at == original


def test_timestamps_come_back_timezone_aware(temp_db):
    """SQLite drops the offset; UtcDateTime puts it back, so date maths works."""
    job = _add()
    stored = repo.get_job(job.id)
    assert stored is not None
    assert stored.first_seen_at.tzinfo is not None
    assert stored.first_seen_at.utcoffset() == timedelta(0)


def test_recency_filter_uses_real_dates(temp_db):
    old = _add(title="Ancient Engineer")
    _add()
    with db_module.session_scope() as session:
        row = session.get(type(old), old.id)
        row.first_seen_at = datetime.now(UTC) - timedelta(days=90)

    recent = repo.search_jobs(posted_since_days=7)
    assert [job.title for job in recent] == ["DevOps Engineer"]


def test_different_roles_are_separate_rows(temp_db):
    _add()
    _add(title="Site Reliability Engineer")
    assert repo.count_jobs() == 2


# ------------------------------------------------------------------ search


def test_search_filters_by_profile(temp_db):
    _add()
    _add(title="Security Engineer", profile=Profile.AUTOMOTIVE_CYBER)
    assert len(repo.search_jobs(profile=Profile.DEVOPS)) == 1


def test_search_keywords_are_conjunctive(temp_db):
    _add(description="Kubernetes and Terraform")
    _add(title="Cloud Engineer", description="Kubernetes only")
    assert len(repo.search_jobs(keywords=["Kubernetes"])) == 2
    assert len(repo.search_jobs(keywords=["Kubernetes", "Terraform"])) == 1


def test_search_location_is_case_insensitive_substring(temp_db):
    _add()
    assert len(repo.search_jobs(location="stuttg")) == 1


def test_search_orders_scored_jobs_first(temp_db):
    low = _add(title="Cloud Engineer")
    high = _add(title="Platform Engineer")
    repo.set_fit_score(low.id, 0.30)
    repo.set_fit_score(high.id, 0.90)
    assert next(job.id for job in repo.search_jobs()) == high.id


def test_search_respects_min_fit(temp_db):
    job = _add()
    repo.set_fit_score(job.id, 0.42)
    assert len(repo.search_jobs(min_fit=0.5)) == 0
    assert len(repo.search_jobs(min_fit=0.4)) == 1


def test_search_by_status_joins_applications(temp_db):
    applied = _add()
    _add(title="Platform Engineer")
    repo.set_application_status(applied.id, ApplicationStatus.APPLIED)
    found = repo.search_jobs(status=ApplicationStatus.APPLIED)
    assert [job.id for job in found] == [applied.id]


def test_search_limit_is_honoured(temp_db):
    for index in range(5):
        _add(title=f"Engineer {index}")
    assert len(repo.search_jobs(limit=2)) == 2


# ------------------------------------------------------------------ funnel


def test_status_update_is_idempotent_per_job(temp_db):
    job = _add()
    repo.set_application_status(job.id, ApplicationStatus.INTERESTED)
    repo.set_application_status(job.id, ApplicationStatus.APPLIED, note="sent via portal")
    rows = repo.list_applications()
    assert len(rows) == 1
    assert rows[0].status == ApplicationStatus.APPLIED
    assert rows[0].note == "sent via portal"


def test_status_cannot_be_set_on_a_job_that_does_not_exist(temp_db):
    """Otherwise an orphan application row is created, the funnel counts drift,
    and nothing ever raises. SQLite does not enforce foreign keys by default,
    so this is checked in the repository as well as by the pragma."""
    from career_copilot.storage.db import StorageError

    with pytest.raises(StorageError) as excinfo:
        repo.set_application_status("not-a-real-id", ApplicationStatus.APPLIED)
    assert "no job stored" in str(excinfo.value.detail)
    assert repo.funnel_counts()["applied"] == 0


def test_funnel_counts_include_every_status(temp_db):
    job = _add()
    repo.set_application_status(job.id, ApplicationStatus.INTERVIEW)
    counts = repo.funnel_counts()
    assert set(counts) == {str(s) for s in ApplicationStatus}
    assert counts["interview"] == 1
    assert counts["offer"] == 0


def test_get_job_returns_none_for_unknown_id(temp_db):
    assert repo.get_job("does-not-exist") is None


def test_job_rows_survive_detachment(temp_db):
    """Rows are expunged before they leave the repository; reading a
    relationship afterwards must not explode."""
    job = _add()
    repo.set_application_status(job.id, ApplicationStatus.APPLIED)
    stored = repo.get_job(job.id)
    assert stored is not None
    assert stored.application is not None
    assert stored.application.status == ApplicationStatus.APPLIED


# ------------------------------------------------------ concurrency, the scar


def test_the_engine_is_configured_for_concurrent_readers(temp_db):
    """Regression: the Jobs page 500'd whenever a fetch was in flight.

    A sync writes one posting per transaction in a background thread. In the
    default rollback-journal mode that holds an exclusive lock on the whole
    file, so the list endpoint's read raised "database is locked", which became
    StorageError, which is absent from the API error mapping and so fell
    through to a bare HTTP 500.
    """
    from sqlalchemy import text

    with db_module.get_engine().connect() as connection:
        mode = connection.execute(text("PRAGMA journal_mode")).scalar()
        timeout = connection.execute(text("PRAGMA busy_timeout")).scalar()

    assert str(mode).lower() == "wal"
    assert int(timeout or 0) >= 5000


def test_a_read_during_an_open_write_transaction_succeeds(temp_db):
    """The property the fix exists for, exercised rather than asserted about."""
    _add()

    with db_module.session_scope() as writing:
        writing.add(
            Job(
                id="held-open",
                source="test",
                title="Second",
                company="Acme",
                description="held open on purpose",
                first_seen_at=datetime.now(UTC),
            )
        )
        writing.flush()  # takes the write lock, still uncommitted

        # This is exactly what the Jobs page does while a sync is running.
        assert repo.count_jobs() >= 1
