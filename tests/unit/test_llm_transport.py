"""How the connection to the model provider is made and kept.

This exists because of a measurement. On one machine every model call that
followed the cross-encoder took about 43 seconds, and every call that followed
another call took one. Twenty-five seconds of doing *nothing* reproduced it, so
it was not the CPU and not the reranker: the connection was being dropped in
the gap, and rebuilding one from Python was what cost the time.

Both settings here address that, and both have a failure mode if they are
wrong, which is why they are settings rather than constants: a long keepalive
on a server with a short idle timeout wastes a round trip, and binding to IPv4
on an IPv6-only network makes the application unreachable rather than fast.

Nothing here opens a socket. What is under test is the decision - which
options are handed to the transport - not whether the network works.
"""

from __future__ import annotations

import pytest

from career_copilot.core.config import get_settings
from career_copilot.core.errors import ConfigError
from career_copilot.core.llm import _http_client, _sdk_http_module, _transport_options


@pytest.fixture(autouse=True)
def _settings(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-test-not-a-real-key")
    monkeypatch.setenv("CC_MODEL", "openai/gpt-4o-mini")
    monkeypatch.setenv("CC_DATA_DIR", str(tmp_path))
    # Set, never deleted - a deleted variable falls through to `.env`.
    monkeypatch.setenv("CC_FORCE_IPV4", "false")
    monkeypatch.setenv("CC_HTTP_KEEPALIVE_SECONDS", "60")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_the_sdk_accepts_the_client_we_build():
    """The test that was missing, and the bug it would have caught.

    Older OpenAI SDKs check `isinstance(http_client, httpx.Client)`; newer ones
    want `httpx2`. Both are installed in some environments, so picking one by
    reading the source of whichever happens to be on the developer's machine
    is guesswork - and guessing wrong is a `TypeError` on the first model call,
    in front of whoever is watching.

    Constructing the real client is the only check that means anything. No
    network: `OpenAI(...)` does not call out.
    """
    from openai import OpenAI

    client = _http_client(get_settings())
    assert client is not None

    OpenAI(api_key="sk-test", base_url="https://example.invalid/v1", http_client=client)


def test_an_unknown_sdk_layout_costs_the_settings_and_nothing_else(monkeypatch):
    """If the SDK's internals move, the application still has to work.

    Losing the connection tuning is a performance regression. Raising here
    would be an outage, and one caused by an optimisation.
    """
    import career_copilot.core.llm as llm_module

    monkeypatch.setattr(llm_module, "_sdk_http_module", lambda: None)

    assert llm_module._http_client(get_settings()) is None


def test_the_library_is_identified_from_the_sdk_itself():
    module = _sdk_http_module()

    assert module is not None
    assert module.__name__ in {"httpx", "httpx2"}
    # Whatever it is, it has to offer the three things the client is built from.
    assert all(hasattr(module, attribute) for attribute in ("Client", "Limits", "HTTPTransport"))


def test_connections_outlive_a_reranking_pass():
    """The default has to be longer than the gap it is there to survive.

    A turn reranks for seven to twenty-five seconds between model calls. The
    library default is five, which expires the connection every single time.
    """
    options = _transport_options(get_settings())

    assert options["keepalive_expiry"] == 60.0
    assert options["keepalive_expiry"] > 25


def test_ipv4_is_not_forced_unless_asked():
    """Off by default, and the default matters more than the option.

    A machine on an IPv6-only network that got this silently would not be slow,
    it would be unable to reach the provider at all.
    """
    assert _transport_options(get_settings())["local_address"] is None


def test_forcing_ipv4_binds_the_socket_to_it(monkeypatch):
    """Binding to an IPv4 address is what stops a dead IPv6 route being tried.

    Python connects to resolved addresses in order and waits out a TCP timeout
    on each; curl races the families and never notices one of them is dead.
    That difference is the whole 43 seconds.
    """
    monkeypatch.setenv("CC_FORCE_IPV4", "true")
    get_settings.cache_clear()

    assert _transport_options(get_settings())["local_address"] == "0.0.0.0"


def test_the_keepalive_is_configurable(monkeypatch):
    monkeypatch.setenv("CC_HTTP_KEEPALIVE_SECONDS", "120")
    get_settings.cache_clear()

    assert _transport_options(get_settings())["keepalive_expiry"] == 120.0


def test_a_keepalive_of_zero_is_refused(monkeypatch):
    """Zero would mean "close it immediately", which is the bug, not a setting."""
    monkeypatch.setenv("CC_HTTP_KEEPALIVE_SECONDS", "0")
    get_settings.cache_clear()

    with pytest.raises(ConfigError):
        get_settings()


def test_every_option_is_one_the_installed_transport_knows():
    """A name that the installed library does not have is a first-call crash.

    Checked against whichever library the SDK actually uses, not against the
    one that happened to be imported while this was written.
    """
    import inspect

    module = _sdk_http_module()
    assert module is not None

    transport = set(inspect.signature(module.HTTPTransport.__init__).parameters)
    limits = set(inspect.signature(module.Limits.__init__).parameters)

    for option in _transport_options(get_settings()):
        assert option in transport or option in limits, option
