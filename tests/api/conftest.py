"""Fixtures for the HTTP tests.

These exercise the transport, not the agent. The agent gets a stub in every
test that reaches a route which would otherwise call one, because what is
being checked here is that a turn's progress reaches the wire in the right
shape - not that the model answers well, which is the evaluation suite's job.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from career_copilot.api import threads
from career_copilot.api.app import create_app
from career_copilot.core.config import get_settings
from career_copilot.storage import db as db_module


@pytest.fixture()
def api_settings(tmp_path, monkeypatch):
    """A throwaway data directory, so no test writes into the real one."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-test-not-a-real-key")
    monkeypatch.setenv("CC_MODEL", "openai/gpt-4o-mini")
    monkeypatch.setenv("CC_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CC_CHROMA_DIR", str(tmp_path / "chroma"))
    monkeypatch.setenv("CC_DB_PATH", str(tmp_path / "career_copilot.db"))
    monkeypatch.setenv("CC_LOG_LEVEL", "WARNING")
    monkeypatch.setenv("CC_LOG_JSON", "false")
    # The app warms the retrieval models on startup. Not here: `TestClient` as
    # a context manager runs the lifespan, and every test would start its own
    # transformer download.
    monkeypatch.setenv("CC_WARM_MODELS", "false")
    # Tracing is forced off for the whole suite in tests/conftest.py. It is not
    # deleted here: removing the variable would fall through to `.env`, and a
    # machine with tracing configured would then fail the health-check test.

    get_settings.cache_clear()
    # The engine is cached and holds the path it was built with, so moving
    # `CC_DB_PATH` is not enough on its own - without this, one test's rows are
    # still there in the next test's "empty" database.
    db_module.reset_engine()
    threads.clear()
    yield get_settings()
    get_settings.cache_clear()
    db_module.reset_engine()
    threads.clear()


@pytest.fixture()
def client(api_settings):
    with TestClient(create_app()) as test_client:
        yield test_client


def sse_events(text: str) -> list[dict]:
    """Parse an SSE body into the events it carried.

    Written by hand rather than with a library: the client parses these frames
    by hand too, and a test that used a more forgiving parser than the browser
    would pass on a stream the browser could not read.
    """
    events: list[dict] = []
    for frame in text.split("\n\n"):
        payload = "".join(
            line[len("data:") :].strip() for line in frame.splitlines() if line.startswith("data:")
        )
        if payload:
            events.append(json.loads(payload))
    return events
