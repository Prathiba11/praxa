from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
import pytest
from openai import APITimeoutError, AuthenticationError, RateLimitError, UnprocessableEntityError

from career_copilot.core.config import get_settings
from career_copilot.core.errors import ConfigError, LLMError, RateLimitedError
from career_copilot.core.llm import chat, stream_chat

FAKE_KEY = "sk-or-v1-SUPERSECRET"


SESSION = "test-session"


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENROUTER_API_KEY", FAKE_KEY)
    monkeypatch.setenv("CC_MODEL", "openai/gpt-4o-mini")
    # `chat` records usage itself now; keep that out of the real data directory.
    monkeypatch.setenv("CC_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _http_response(status: int, headers: dict[str, str] | None = None) -> httpx.Response:
    request = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
    return httpx.Response(status, request=request, headers=headers or {})


def _client_raising(exc: Exception) -> MagicMock:
    client = MagicMock()
    client.chat.completions.create.side_effect = exc
    return client


def _client_returning(content: str = "Hello", tool_calls: list | None = None) -> MagicMock:
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    choice = SimpleNamespace(message=message, finish_reason="stop")
    usage = SimpleNamespace(prompt_tokens=10, completion_tokens=5)
    response = SimpleNamespace(
        choices=[choice], model="openai/gpt-4o-mini", usage=usage, id="gen-abc123"
    )
    client = MagicMock()
    client.chat.completions.create.return_value = response
    return client


# ---------------------------------------------------------------- mapping


def test_rate_limit_maps_to_rate_limited_error():
    exc = RateLimitError(
        "rate limited", response=_http_response(429, {"retry-after": "7"}), body=None
    )
    with (
        patch("career_copilot.core.llm.get_client", return_value=_client_raising(exc)),
        pytest.raises(RateLimitedError) as info,
    ):
        chat([{"role": "user", "content": "hi"}], session_id=SESSION)
    assert info.value.retry_after == 7.0


def test_auth_failure_maps_to_config_error():
    exc = AuthenticationError("bad key", response=_http_response(401), body=None)
    with (
        patch("career_copilot.core.llm.get_client", return_value=_client_raising(exc)),
        pytest.raises(ConfigError),
    ):
        chat([{"role": "user", "content": "hi"}], session_id=SESSION)


def test_timeout_is_retryable():
    exc = APITimeoutError(request=httpx.Request("POST", "https://openrouter.ai"))
    with (
        patch("career_copilot.core.llm.get_client", return_value=_client_raising(exc)),
        pytest.raises(LLMError) as info,
    ):
        chat([{"role": "user", "content": "hi"}], session_id=SESSION)
    assert info.value.retryable is True


def test_422_is_not_retryable():
    exc = UnprocessableEntityError("bad body", response=_http_response(422), body=None)
    with (
        patch("career_copilot.core.llm.get_client", return_value=_client_raising(exc)),
        pytest.raises(LLMError) as info,
    ):
        chat([{"role": "user", "content": "hi"}], session_id=SESSION)
    assert info.value.retryable is False


@pytest.mark.parametrize(
    "exc",
    [
        RateLimitError("x", response=_http_response(429), body=None),
        AuthenticationError("x", response=_http_response(401), body=None),
        UnprocessableEntityError("x", response=_http_response(422), body=None),
        APITimeoutError(request=httpx.Request("POST", "https://openrouter.ai")),
    ],
)
def test_no_error_leaks_the_key_or_url(exc):
    """Earlier review finding #1: nothing sensitive may escape this module."""
    with (
        patch("career_copilot.core.llm.get_client", return_value=_client_raising(exc)),
        pytest.raises(Exception) as info,
    ):
        chat([{"role": "user", "content": "hi"}], session_id=SESSION)

    err = info.value
    for text in (err.user_message, err.detail, str(err)):
        assert "SUPERSECRET" not in text
        assert "openrouter.ai" not in text


# ---------------------------------------------------------------- success


def test_successful_call_returns_typed_result():
    with patch("career_copilot.core.llm.get_client", return_value=_client_returning()):
        result = chat([{"role": "user", "content": "hi"}], session_id=SESSION)

    assert result.content == "Hello"
    assert result.prompt_tokens == 10
    assert result.completion_tokens == 5
    assert result.finish_reason == "stop"
    assert result.generation_id == "gen-abc123"
    assert result.latency_ms > 0
    assert result.tool_calls == []


def test_tool_calls_are_parsed():
    raw = [
        SimpleNamespace(
            id="call_1",
            function=SimpleNamespace(name="get_weather", arguments='{"city": "Berlin"}'),
        )
    ]
    client = _client_returning(content=None, tool_calls=raw)
    with patch("career_copilot.core.llm.get_client", return_value=client):
        result = chat(
            [{"role": "user", "content": "weather?"}],
            session_id=SESSION,
            tools=[{"type": "function"}],
        )

    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].name == "get_weather"
    assert result.tool_calls[0].arguments == '{"city": "Berlin"}'


# ------------------------------------------------------------------ streaming


def _chunk(content=None, *, usage=None, finish=None, model="openai/gpt-4o-mini"):
    """One SSE chunk. A content chunk carries no usage and vice versa."""
    if usage is not None:
        return SimpleNamespace(choices=[], usage=usage, id="gen-abc123", model=model)
    delta = SimpleNamespace(content=content)
    choice = SimpleNamespace(delta=delta, finish_reason=finish)
    return SimpleNamespace(choices=[choice], usage=None, id="gen-abc123", model=model)


def _client_streaming(pieces=("Hel", "lo", " there"), *, usage=True):
    chunks = [_chunk(piece) for piece in pieces]
    chunks.append(_chunk(None, finish="stop"))
    if usage:
        chunks.append(_chunk(usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5)))
    client = MagicMock()
    client.chat.completions.create.return_value = iter(chunks)
    return client


def test_streaming_yields_the_answer_in_pieces():
    """The reviewer's point: the answer used to arrive in one frame."""
    with patch("career_copilot.core.llm.get_client", return_value=_client_streaming()):
        pieces = list(stream_chat([{"role": "user", "content": "hi"}], session_id=SESSION))

    assert pieces == ["Hel", "lo", " there"]
    assert "".join(pieces) == "Hello there"


def test_streaming_records_the_same_usage_as_a_plain_call():
    """The assertion that makes this safe to ship.

    `chat` exists to make the budget check and the usage record impossible to
    skip. A streamed path that under-counted would break that guarantee exactly
    where nobody looks - so the two are compared directly rather than trusted.
    """
    from career_copilot.core.usage import session_totals

    with patch("career_copilot.core.llm.get_client", return_value=_client_returning()):
        chat([{"role": "user", "content": "hi"}], session_id="plain")
    plain = session_totals("plain")

    with patch("career_copilot.core.llm.get_client", return_value=_client_streaming()):
        list(stream_chat([{"role": "user", "content": "hi"}], session_id="streamed"))
    streamed = session_totals("streamed")

    assert streamed.prompt_tokens == plain.prompt_tokens == 10
    assert streamed.completion_tokens == plain.completion_tokens == 5


def test_streaming_asks_for_usage_in_the_final_chunk():
    """Without `include_usage` a streamed call reports nothing and the ledger
    silently under-counts. This pins the flag rather than the behaviour it
    produces, because the provider is the thing that honours it."""
    client = _client_streaming()
    with patch("career_copilot.core.llm.get_client", return_value=client):
        list(stream_chat([{"role": "user", "content": "hi"}], session_id=SESSION))

    kwargs = client.chat.completions.create.call_args.kwargs
    assert kwargs["stream"] is True
    assert kwargs["stream_options"] == {"include_usage": True}
    # And no tools: streaming is for prose, not for deciding what to call.
    assert "tools" not in kwargs


def test_a_stream_with_no_usage_chunk_still_completes():
    """It must not crash, and it must say the turn went uncounted."""
    with patch("career_copilot.core.llm.get_client", return_value=_client_streaming(usage=False)):
        pieces = list(stream_chat([{"role": "user", "content": "hi"}], session_id=SESSION))
    assert "".join(pieces) == "Hello there"


def test_streaming_checks_the_budget_before_the_request():
    """Same guarantee as `chat`: a refused turn costs nothing."""
    client = _client_streaming()
    with (
        patch("career_copilot.core.llm.get_client", return_value=client),
        patch("career_copilot.core.llm.check_budget", side_effect=RuntimeError("ceiling")),
        pytest.raises(RuntimeError, match="ceiling"),
    ):
        list(stream_chat([{"role": "user", "content": "hi"}], session_id=SESSION))

    client.chat.completions.create.assert_not_called()


def test_streaming_maps_errors_the_same_way():
    """`_create` is shared, so a 429 means the same thing on both paths."""
    exc = RateLimitError("rate limited", response=_http_response(429), body=None)
    with (
        patch("career_copilot.core.llm.get_client", return_value=_client_raising(exc)),
        pytest.raises(RateLimitedError),
    ):
        list(stream_chat([{"role": "user", "content": "hi"}], session_id=SESSION))
