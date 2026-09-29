"""The jobs endpoints, against a real SQLite database.

Nothing is stubbed here except the clock, because there is nothing expensive to
stub: this router is SQL and serialisation. That is the property most worth
protecting - if a test in this file ever needs a scripted model, something that
belongs to the agent has leaked into the page.
"""

from __future__ import annotations

import pytest

from career_copilot.core.types import ApplicationStatus, Profile
from career_copilot.storage import jobs as repo
from career_copilot.storage.db import init_db


@pytest.fixture()
def seeded(api_settings):
    """Three postings with different profiles, places and states."""
    init_db()
    bosch = repo.upsert_job(
        source="test",
        title="Platform Engineer",
        company="Bosch",
        location="Stuttgart",
        description="Kubernetes, Terraform and GitLab CI for vehicle telemetry.",
        profile=Profile.DEVOPS,
    )
    conti = repo.upsert_job(
        source="test",
        title="Security Engineer",
        company="Continental",
        location="Regensburg",
        description="ISO/SAE 21434, TARA and UNECE R155 for ECU platforms.",
        profile=Profile.AUTOMOTIVE_CYBER,
    )
    repo.upsert_job(
        source="test",
        title="ML Engineer",
        company="Aleph Alpha",
        location="Heidelberg",
        description="Retrieval pipelines and evaluation for language models.",
        profile=Profile.AI_ENG,
    )
    repo.set_fit_score(bosch.id, 82.0)
    repo.set_application_status(conti.id, ApplicationStatus.APPLIED)
    return {"bosch": bosch.id, "conti": conti.id}


# -------------------------------------------------------------------- listing


def test_every_saved_posting_comes_back(client, seeded):
    body = client.get("/api/jobs").json()

    assert {row["company"] for row in body} == {"Bosch", "Continental", "Aleph Alpha"}


def test_the_best_fit_is_first(client, seeded):
    """A ranked list is the point of scoring. An unranked one is a table."""
    body = client.get("/api/jobs").json()

    assert body[0]["company"] == "Bosch"
    assert body[0]["fitScore"] == 82.0


def test_rows_are_camel_case(client, seeded):
    row = client.get("/api/jobs").json()[0]

    assert "fitScore" in row
    assert "firstSeenAt" in row
    assert "fit_score" not in row


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({"profile": "devops"}, {"Bosch"}),
        ({"location": "Regensburg"}, {"Continental"}),
        ({"company": "aleph"}, {"Aleph Alpha"}),
        ({"status": "applied"}, {"Continental"}),
        ({"query": "Kubernetes"}, {"Bosch"}),
        ({"minFit": 50}, {"Bosch"}),
    ],
)
def test_each_filter_narrows_to_what_it_names(client, seeded, params, expected):
    body = client.get("/api/jobs", params=params).json()

    assert {row["company"] for row in body} == expected


def test_filters_combine_rather_than_replace(client, seeded):
    body = client.get("/api/jobs", params={"profile": "devops", "location": "Regensburg"}).json()

    assert body == []


def test_an_untriaged_posting_has_no_status(client, seeded):
    """Absence is a real state - it means nobody has looked at it yet - and it
    has to survive the round trip as null rather than as a default."""
    row = next(r for r in client.get("/api/jobs").json() if r["company"] == "Aleph Alpha")

    assert row["status"] is None


# --------------------------------------------------------------------- detail


def test_the_detail_view_carries_the_posting_text(client, seeded):
    """It is what a fit score was computed from. Someone checking the score
    needs to read the same thing the model did."""
    body = client.get(f"/api/jobs/{seeded['bosch']}").json()

    assert "Terraform" in body["description"]


def test_an_unknown_job_is_a_404_in_the_usual_envelope(client, seeded):
    response = client.get("/api/jobs/not-a-real-id")

    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


# --------------------------------------------------------------------- funnel


def test_the_funnel_reports_every_stage_including_the_empty_ones(client, seeded):
    body = client.get("/api/jobs/funnel").json()

    assert body["counts"]["applied"] == 1
    assert body["counts"]["offer"] == 0
    assert body["totalJobs"] == 3


def test_funnel_is_not_read_as_a_job_id(client, seeded):
    """Route order. Declared after `/{job_id}` this would 404 forever."""
    assert client.get("/api/jobs/funnel").status_code == 200


# --------------------------------------------------------------------- status


def test_moving_an_application_along_the_funnel(client, seeded):
    response = client.post(
        f"/api/jobs/{seeded['bosch']}/status",
        json={"status": "interview", "note": "second round on Tuesday"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "interview"
    assert response.json()["note"] == "second round on Tuesday"


def test_a_status_change_shows_up_in_the_funnel(client, seeded):
    client.post(f"/api/jobs/{seeded['bosch']}/status", json={"status": "offer"})

    assert client.get("/api/jobs/funnel").json()["counts"]["offer"] == 1


def test_an_invented_status_is_refused(client, seeded):
    """The funnel is a closed set. A typo must not create a fourth stage."""
    response = client.post(f"/api/jobs/{seeded['bosch']}/status", json={"status": "vibes"})

    assert response.status_code == 422
    assert response.json()["code"] == "invalid_request"


def test_a_status_on_an_unknown_job_is_a_404(client, seeded):
    response = client.post("/api/jobs/nope/status", json={"status": "applied"})

    assert response.status_code == 404


# ---------------------------------------------------------------------- paste


PASTED = {
    "title": "Cybersecurity Engineer",
    "company": "ZF",
    "location": "Friedrichshafen",
    "description": "Threat analysis and risk assessment to ISO/SAE 21434 for braking ECUs.",
    "profile": "automotive_cyber",
}


def test_a_pasted_posting_is_saved_and_returned(client, api_settings):
    response = client.post("/api/jobs/paste", json=PASTED)

    assert response.status_code == 201
    assert response.json()["company"] == "ZF"
    assert response.json()["profile"] == "automotive_cyber"


def test_a_pasted_posting_is_attributed_to_the_paste(client, api_settings):
    """Attribution is a licence condition on the boards this reads, so the
    source is set here and never taken from the request."""
    body = client.post("/api/jobs/paste", json=PASTED).json()

    assert body["source"] == "pasted"


def test_pasting_the_same_posting_twice_does_not_duplicate_it(client, api_settings):
    first = client.post("/api/jobs/paste", json=PASTED).json()
    second = client.post("/api/jobs/paste", json=PASTED).json()

    assert first["id"] == second["id"]
    assert len(client.get("/api/jobs").json()) == 1


@pytest.mark.parametrize(
    "payload",
    [
        {**PASTED, "description": "too short"},
        {"description": ""},
        {**PASTED, "profile": "wizardry"},
        {"title": "No description at all"},
    ],
)
def test_a_malformed_posting_is_refused(client, api_settings, payload):
    """What is still invalid: no usable text, or a profile that does not exist.

    An empty title and a missing company used to be in this list. They are not
    any more, on purpose - requiring them before anything could be saved made
    the quickest path the most tedious one, and both are now read out of the
    pasted text. The two cases below record that they are accepted, so the
    change is a decision in the suite rather than a gap in it.
    """
    assert client.post("/api/jobs/paste", json=payload).status_code == 422


@pytest.mark.parametrize("payload", [{**PASTED, "title": ""}, {"description": "x" * 40}])
def test_a_posting_without_a_title_or_company_is_accepted(client, api_settings, payload):
    """The rule the two cases above used to enforce, now retired deliberately."""
    response = client.post("/api/jobs/paste", json=payload)
    assert response.status_code == 201
    body = response.json()
    # Never blank, and never invented: a wrong employer would change the
    # deduplication fingerprint and store one job as two rows.
    assert body["title"]
    assert body["company"]


def test_pasting_does_not_invent_a_status(client, api_settings):
    """Saving a posting is not applying for it."""
    assert client.post("/api/jobs/paste", json=PASTED).json()["status"] is None


def test_a_paste_is_classified_when_no_profile_is_chosen(client):
    """Regression: a paste was stored with no profile and vanished from the list.

    The list hides postings the classifier could not place, so a paste that was
    never classified saved successfully and then could not be found anywhere.
    """
    body = (
        "We are hiring a DevOps Engineer. You will run our Kubernetes clusters, "
        "write Terraform, maintain GitLab CI pipelines, and own observability "
        "with Prometheus and Grafana. Site reliability practices throughout."
    )
    response = client.post(
        "/api/jobs/paste",
        json={
            "title": "DevOps Engineer",
            "company": "S-Management Services GmbH",
            "description": body,
        },
    )
    assert response.status_code == 201
    assert response.json()["profile"] == "devops"


def test_a_chosen_profile_beats_the_classifier(client):
    """The person pasting knows better than the keyword scorer."""
    body = (
        "We are hiring a DevOps Engineer. You will run our Kubernetes clusters, "
        "write Terraform, maintain GitLab CI pipelines, and own observability "
        "with Prometheus and Grafana. Site reliability practices throughout."
    )
    response = client.post(
        "/api/jobs/paste",
        json={
            "title": "DevOps Engineer",
            "company": "Acme",
            "description": body,
            "profile": "ai_eng",
        },
    )
    assert response.status_code == 201
    assert response.json()["profile"] == "ai_eng"


def test_a_pasted_posting_reaches_the_default_list(client):
    """The end of the journey the bug broke: paste it, then see it."""
    body = (
        "Automotive cybersecurity engineer. ISO 21434 and UNECE R155 work, TARA "
        "threat analysis, CSMS evidence, ECU penetration testing on vehicle "
        "platforms, AUTOSAR and CAN bus exposure."
    )
    client.post(
        "/api/jobs/paste",
        json={"title": "Security Engineer Automotive", "company": "Bosch", "description": body},
    )
    listed = client.get("/api/jobs")
    assert listed.status_code == 200
    assert any(job["company"] == "Bosch" for job in listed.json())


_BODY = (
    "We are hiring a DevOps Engineer. You will run our Kubernetes clusters, "
    "write Terraform, maintain GitLab CI pipelines, and own observability "
    "with Prometheus and Grafana. Site reliability practices throughout."
)


def test_only_the_text_is_required(client):
    """The quickest path - copy the posting, paste it - must be the easy one."""
    response = client.post("/api/jobs/paste", json={"description": _BODY})
    assert response.status_code == 201
    assert response.json()["profile"] == "devops"


def test_the_role_and_employer_are_read_out_of_the_paste(client):
    response = client.post(
        "/api/jobs/paste",
        json={"description": f"DevOps Engineer at Robert Bosch GmbH\n\n{_BODY}"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "DevOps Engineer"
    assert body["company"] == "Robert Bosch GmbH"


def test_a_role_and_employer_on_two_lines_are_read(client):
    response = client.post(
        "/api/jobs/paste",
        json={"description": f"Senior DevOps Engineer\nAuxmoney GmbH\n\n{_BODY}"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "Senior DevOps Engineer"
    assert body["company"] == "Auxmoney GmbH"


def test_what_the_user_typed_beats_what_was_read(client):
    response = client.post(
        "/api/jobs/paste",
        json={
            "description": f"DevOps Engineer at Robert Bosch GmbH\n\n{_BODY}",
            "company": "Bosch Engineering GmbH",
        },
    )
    assert response.status_code == 201
    assert response.json()["company"] == "Bosch Engineering GmbH"


def test_an_unreadable_paste_gets_a_placeholder_not_a_guess(client):
    """A wrong company changes the fingerprint and stores one job as two."""
    response = client.post("/api/jobs/paste", json={"description": _BODY})
    assert response.status_code == 201
    assert response.json()["company"] == "Unknown company"


def test_the_fit_filter_speaks_percentages(client):
    """Regression: the filter compared 70 against a stored 0.7 and matched nothing.

    `Job.fit_score` is the 0-1 fraction the model produced. The query parameter
    is a percentage, because that is what the number on a card says.
    """
    from career_copilot.storage import jobs as store

    paste = client.post(
        "/api/jobs/paste",
        json={"description": f"DevOps Engineer at Bosch\n\n{_BODY}"},
    )
    assert paste.status_code == 201
    store.set_fit_score(paste.json()["id"], 0.7)

    assert any(job["fitScore"] == 0.7 for job in client.get("/api/jobs?minFit=70").json())
    assert any(job["fitScore"] == 0.7 for job in client.get("/api/jobs?minFit=50").json())
    assert not any(job["fitScore"] == 0.7 for job in client.get("/api/jobs?minFit=90").json())


def test_a_stored_score_stays_a_fraction(client):
    """The one invariant the display bug came from: storage is 0-1, never 0-100."""
    from career_copilot.storage import jobs as store

    paste = client.post(
        "/api/jobs/paste",
        json={"description": f"DevOps Engineer at Bosch\n\n{_BODY}"},
    )
    store.set_fit_score(paste.json()["id"], 0.7)

    listed = client.get("/api/jobs").json()
    scored = [job for job in listed if job["fitScore"] is not None]
    assert scored, "expected the scored posting in the list"
    assert all(0.0 <= job["fitScore"] <= 1.0 for job in scored)
