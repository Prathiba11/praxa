"""The two endpoints that never call a model.

Both are read-only and cheap, which is what makes them worth testing carefully:
they are what a reviewer, a container healthcheck and the cost panel all hit,
and all three would be misled by a plausible wrong number.
"""

from __future__ import annotations

import pytest

from career_copilot.core import usage as usage_module
from career_copilot.core.config import get_settings


def test_health_reports_ok_and_says_whether_tracing_is_on(client):
    body = client.get("/api/health").json()

    assert body["status"] == "ok"
    assert body["version"]
    assert body["tracing"] is False


def test_usage_without_a_thread_reports_no_session_spend(client):
    body = client.get("/api/usage").json()

    assert body["sessionTokens"] == 0
    assert body["sessionCostUsd"] == 0.0
    assert body["unpricedCalls"] == 0


def test_usage_is_camel_case_because_the_client_is_a_browser(client):
    body = client.get("/api/usage").json()

    assert "sessionCostUsd" in body
    assert "session_cost_usd" not in body


def test_usage_counts_only_the_thread_it_was_asked_about(client):
    usage_module.record(
        session_id="thread-a",
        operation="chat",
        model="openai/gpt-4o-mini",
        prompt_tokens=1000,
        completion_tokens=200,
    )
    usage_module.record(
        session_id="thread-b",
        operation="chat",
        model="openai/gpt-4o-mini",
        prompt_tokens=9000,
        completion_tokens=9000,
    )

    body = client.get("/api/usage", params={"threadId": "thread-a"}).json()

    assert body["sessionTokens"] == 1200
    assert body["sessionCostUsd"] == pytest.approx(0.00027)


def test_remaining_budget_is_whichever_ceiling_bites_first(client, monkeypatch):
    """A client can mint a new thread id; it cannot mint a new month.

    So the number shown has to be the monthly headroom whenever that is the
    smaller one, or the panel will promise spend that the next turn refuses.
    """
    monkeypatch.setenv("CC_SESSION_BUDGET_USD", "5.0")
    monkeypatch.setenv("CC_MONTHLY_BUDGET_USD", "0.10")
    from career_copilot.core.config import get_settings

    get_settings.cache_clear()

    usage_module.record(
        session_id="thread-a",
        operation="chat",
        model="openai/gpt-4o-mini",
        prompt_tokens=100000,
        completion_tokens=0,
    )

    body = client.get("/api/usage", params={"threadId": "thread-a"}).json()

    assert body["sessionCostUsd"] == pytest.approx(0.015)
    assert body["budgetRemainingUsd"] == pytest.approx(0.085)  # monthly, not session


def test_a_call_with_no_known_price_is_reported_rather_than_hidden(client):
    """Zero is a defensible figure only next to a count of what it left out."""
    usage_module.record(
        session_id="thread-a",
        operation="chat",
        model="some/model-nobody-priced",
        prompt_tokens=5000,
        completion_tokens=500,
    )

    body = client.get("/api/usage", params={"threadId": "thread-a"}).json()

    assert body["sessionCostUsd"] == 0.0
    assert body["unpricedCalls"] == 1


def test_an_unknown_api_path_is_a_404_not_the_app_shell(client):
    """Only the frontend gets the single-page fallback. /api must not."""
    assert client.get("/api/nope").status_code == 404


def test_startup_begins_warming_the_retrieval_models(api_settings, monkeypatch):
    """The lifespan is wired to the warm-up, and this is the only test that says so.

    Every other test forces `CC_WARM_MODELS=false`, for good reason - each one
    builds an app, and a real warm-up would start a transformer download per
    test. The cost of that blanket "off" is that the wiring itself went
    unexercised: `warm_models` was covered, `create_app` calling it was not.
    A lifespan that quietly stopped firing would have broken nothing here.
    """
    from fastapi.testclient import TestClient

    from career_copilot.api import app as app_module

    monkeypatch.setenv("CC_WARM_MODELS", "true")
    get_settings.cache_clear()

    started: list[str] = []
    monkeypatch.setattr(app_module, "warm_in_background", lambda: started.append("warming"))

    with TestClient(app_module.create_app()) as client:
        assert client.get("/api/health").status_code == 200

    assert started == ["warming"]
