"""The developer settings router.

This endpoint writes environment variables into the running process, which is
the documented design - a change here is immediate, complete, and gone on
restart. It also means a test that changes one must pin it first, or the value
outlives the test. `monkeypatch.setenv` before each change is what does that,
and it is the reason these tests set a variable they are about to overwrite.

What is checked: that the model list is closed (the scar this router was built
around), and that temperature and answer length are changeable rather than
merely displayed.
"""

from __future__ import annotations

import pytest

from career_copilot.core.config import get_settings


@pytest.fixture()
def pinned(monkeypatch):
    """Pin the variables this router writes, so no change escapes the test."""
    monkeypatch.setenv("CC_TEMPERATURE", "0.2")
    monkeypatch.setenv("CC_MAX_TOKENS", "1500")
    monkeypatch.setenv("CC_GRADER_MODEL", "openai/gpt-4o-mini")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_the_page_reports_what_the_server_is_running_with(client, api_settings, pinned):
    body = client.get("/api/settings").json()

    assert body["chatModel"] == "openai/gpt-4o-mini"
    assert body["temperature"] == 0.2
    assert body["maxTokens"] == 1500
    assert len(body["models"]) == 4
    assert body["customModel"] is False


def test_the_model_list_is_closed(client, api_settings, pinned):
    """A free-text model id is the bug this router exists because of.

    `CC_GRADER_MODEL` was once any string, was set to an id the account could
    not reach, and grading died silently for days because it fails open. A 400
    here is that story turned into a test.
    """
    response = client.post("/api/settings", json={"chatModel": "acme/does-not-exist"})

    assert response.status_code == 400
    assert client.get("/api/settings").json()["chatModel"] == "openai/gpt-4o-mini"


def test_choosing_another_offered_model_takes_effect_immediately(client, api_settings, pinned):
    body = client.post("/api/settings", json={"chatModel": "anthropic/claude-3.5-haiku"}).json()

    assert body["chatModel"] == "anthropic/claude-3.5-haiku"
    # Read back through a second request, because the point of clearing the
    # settings cache is that the *next* turn sees the change, not that the
    # response echoes what was sent.
    assert client.get("/api/settings").json()["chatModel"] == "anthropic/claude-3.5-haiku"


def test_temperature_is_a_field_rather_than_a_display(client, api_settings, pinned):
    assert client.post("/api/settings", json={"temperature": 0.9}).json()["temperature"] == 0.9
    assert client.get("/api/settings").json()["temperature"] == 0.9


def test_answer_length_is_a_field_rather_than_a_display(client, api_settings, pinned):
    assert client.post("/api/settings", json={"maxTokens": 3000}).json()["maxTokens"] == 3000
    assert client.get("/api/settings").json()["maxTokens"] == 3000


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("temperature", -0.1),
        ("temperature", 2.5),
        ("maxTokens", 10),
        ("maxTokens", 100_000),
    ],
)
def test_both_fields_are_bounded_at_each_end(client, api_settings, pinned, field, value):
    """Not validation for its own sake.

    Below a few hundred tokens a tailored CV is cut off mid-sentence and reads
    as a bug; above a few thousand one turn can eat a real share of the session
    budget. The ceiling is a guard on the bill.
    """
    assert client.post("/api/settings", json={field: value}).status_code == 422


def test_an_empty_change_is_not_an_error(client, api_settings, pinned):
    """The page sends what changed. Sending nothing is a no-op, not a 400."""
    assert client.post("/api/settings", json={}).status_code == 200
