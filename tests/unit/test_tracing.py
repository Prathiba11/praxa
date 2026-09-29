"""Tracing is opt-in, and invisible when it is off.

The guarantee that matters most here is the boring one: someone who clones this
repo, installs it and runs the tests must never need a LangSmith account. Every
test below runs with tracing off except the two that deliberately turn it on.
"""

from __future__ import annotations

import pytest

from career_copilot.core import tracing
from career_copilot.core.config import get_settings

FAKE_KEY = "sk-or-v1-SUPERSECRET"


@pytest.fixture(autouse=True)
def _clean(monkeypatch, tmp_path):
    """A known-off starting point, whatever the developer's `.env` says.

    The settings that switch tracing off are **set**, not deleted. Deleting an
    environment variable does not make a setting unset - pydantic-settings
    falls through to `.env`, so on a machine with tracing configured these
    tests would run with it switched on and fail for a reason that has nothing
    to do with the code. That is exactly what happened once; hence the comment.

    `conftest._no_tracing` already does this for the whole suite. It is
    repeated here because this module is the one that deliberately turns
    tracing on, and its starting point should be readable in its own file.
    """
    monkeypatch.setenv("OPENROUTER_API_KEY", FAKE_KEY)
    monkeypatch.setenv("CC_MODEL", "openai/gpt-4o-mini")
    monkeypatch.setenv("CC_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CC_TRACING_ENABLED", "false")
    monkeypatch.setenv("LANGSMITH_API_KEY", "")
    monkeypatch.setenv("LANGSMITH_ENDPOINT", "")
    monkeypatch.delenv("LANGSMITH_TRACING", raising=False)
    monkeypatch.delenv("LANGSMITH_PROJECT", raising=False)
    get_settings.cache_clear()
    tracing.reset_tracing()
    yield
    get_settings.cache_clear()
    tracing.reset_tracing()


# ------------------------------------------------------------------ off by default


def test_tracing_is_off_unless_asked_for():
    assert tracing.tracing_active() is False


def test_a_flag_without_a_key_stays_off(monkeypatch):
    """Half-configured is off, not broken.

    Someone copying an example .env gets the flag without the key; that must be
    a log line, not a stalled request on every turn.
    """
    monkeypatch.setenv("CC_TRACING_ENABLED", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "")
    get_settings.cache_clear()
    tracing.reset_tracing()

    assert tracing.tracing_active() is False


def test_the_environment_is_untouched_while_off(monkeypatch):
    monkeypatch.setenv("CC_TRACING_ENABLED", "true")
    get_settings.cache_clear()
    tracing.reset_tracing()

    tracing.tracing_active()

    assert "LANGSMITH_TRACING" not in __import__("os").environ


# ------------------------------------------------------------------ no-op behaviour


def test_a_traced_function_behaves_identically_when_off():
    calls: list[int] = []

    @tracing.traced("adder")
    def add(a: int, b: int) -> int:
        calls.append(a + b)
        return a + b

    assert add(2, 3) == 5
    assert add(b=4, a=1) == 5  # keywords survive the wrapper
    assert calls == [5, 5]


def test_a_traced_function_keeps_its_identity():
    @tracing.traced()
    def documented() -> None:
        """Kept so that help() and the docs still work."""

    assert documented.__name__ == "documented"
    assert documented.__doc__ is not None


def test_a_traced_function_still_raises_what_it_raised():
    @tracing.traced("boom")
    def explode() -> None:
        raise ValueError("as designed")

    with pytest.raises(ValueError, match="as designed"):
        explode()


def test_instrument_returns_the_client_unchanged_when_off():
    sentinel = object()
    assert tracing.instrument(sentinel) is sentinel


def test_metadata_is_a_no_op_when_off():
    tracing.add_run_metadata(mode="chat", session_id="abc")  # must not raise


# ------------------------------------------------------------------ switched on


def test_a_key_and_a_flag_turn_it_on(monkeypatch):
    monkeypatch.setenv("CC_TRACING_ENABLED", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "ls__pretend")
    monkeypatch.setenv("LANGSMITH_PROJECT", "praxa-test")
    get_settings.cache_clear()
    tracing.reset_tracing()

    pytest.importorskip("langsmith")

    assert tracing.tracing_active() is True


def test_switching_on_configures_the_sdk(monkeypatch):
    """The SDK reads the environment; settings are what fill it in."""
    import os

    monkeypatch.setenv("CC_TRACING_ENABLED", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "ls__pretend")
    monkeypatch.setenv("LANGSMITH_PROJECT", "praxa-test")
    get_settings.cache_clear()
    tracing.reset_tracing()

    pytest.importorskip("langsmith")
    tracing.tracing_active()

    assert os.environ["LANGSMITH_TRACING"] == "true"
    assert os.environ["LANGSMITH_PROJECT"] == "praxa-test"


# ------------------------------------------------------------------ region


def test_an_eu_workspace_endpoint_is_passed_to_the_sdk(monkeypatch):
    """A workspace on eu.smith.langchain.com needs the EU API host.

    The SDK defaults to the US region, so without this every trace from an EU
    account is rejected at ingest - and the error does not say why.
    """
    import os

    monkeypatch.setenv("CC_TRACING_ENABLED", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "ls__pretend")
    monkeypatch.setenv("LANGSMITH_ENDPOINT", "https://eu.api.smith.langchain.com")
    get_settings.cache_clear()
    tracing.reset_tracing()

    pytest.importorskip("langsmith")
    tracing.tracing_active()

    assert os.environ["LANGSMITH_ENDPOINT"] == "https://eu.api.smith.langchain.com"


def test_the_web_address_is_flagged_rather_than_silently_accepted(monkeypatch, caplog):
    """Using the sign-in URL as the endpoint is the common mistake."""
    monkeypatch.setenv("CC_TRACING_ENABLED", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "ls__pretend")
    monkeypatch.setenv("LANGSMITH_ENDPOINT", "https://eu.smith.langchain.com")
    get_settings.cache_clear()
    tracing.reset_tracing()

    pytest.importorskip("langsmith")
    with caplog.at_level("WARNING"):
        tracing.tracing_active()

    assert any("web address" in record.message for record in caplog.records)


def test_no_endpoint_means_the_sdk_default(monkeypatch):
    """A US workspace needs no endpoint at all, and must not be given one.

    Asserted as "no endpoint reached the SDK" rather than "the name is absent
    from the environment", because the fixture has to put an empty value there
    to stop a configured `.env` leaking its own endpoint in. Empty and absent
    mean the same thing to `_resolve`, which only writes a non-empty one.
    """
    import os

    monkeypatch.setenv("CC_TRACING_ENABLED", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "ls__pretend")
    get_settings.cache_clear()
    tracing.reset_tracing()

    pytest.importorskip("langsmith")
    tracing.tracing_active()

    assert os.environ.get("LANGSMITH_ENDPOINT", "") == ""
