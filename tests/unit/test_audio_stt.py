"""Backend selection and error handling for speech-to-text.

No network and no model. What is worth testing here is the selection logic - a
machine with a key behaves differently from one without, and both have to behave
sensibly - and that every failure mode arrives as a typed error the UI can show
rather than an exception from inside httpx.
"""

from __future__ import annotations

import io
import struct
import wave

import httpx
import pytest

from career_copilot.audio import stt
from career_copilot.audio.stt import AudioError, available, describe, transcribe, wav_seconds

_KEYS = ("GROQ_API_KEY", "OPENAI_API_KEY")


@pytest.fixture(autouse=True)
def no_keys(monkeypatch):
    """Start every test from a machine with no audio credentials."""
    for name in _KEYS:
        monkeypatch.delenv(name, raising=False)


def _wav(seconds: float = 1.0, rate: int = 16000) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(struct.pack("<h", 0) * int(rate * seconds))
    return buffer.getvalue()


def _transport(monkeypatch, handler) -> None:
    """Replace httpx.post with one backed by a mock transport - the same
    network-free approach the job sources use."""

    def _post(url, **kwargs):
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            return client.post(url, **kwargs)

    monkeypatch.setattr(stt.httpx, "post", _post)


# ------------------------------------------------------------------ selection


def test_a_groq_key_wins(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk-test")
    assert "Groq" in stt.get_transcriber().name
    assert available()


def test_groq_is_preferred_over_openai(monkeypatch):
    """Both work; Groq's turbo model is several times faster for this job."""
    monkeypatch.setenv("GROQ_API_KEY", "gsk-test")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert "Groq" in stt.get_transcriber().name


def test_openai_is_used_when_it_is_the_only_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert "OpenAI" in stt.get_transcriber().name


def test_a_blank_key_does_not_count(monkeypatch):
    """An empty value in `.env` is a very common way to have 'a key'."""
    monkeypatch.setenv("GROQ_API_KEY", "   ")
    monkeypatch.setattr(stt.importlib.util, "find_spec", lambda name: None)
    with pytest.raises(AudioError, match="no speech-to-text backend"):
        stt.get_transcriber()


def test_no_backend_at_all_is_a_readable_refusal(monkeypatch):
    monkeypatch.setattr(stt.importlib.util, "find_spec", lambda name: None)
    assert not available()
    assert "faster-whisper" in describe()
    with pytest.raises(AudioError, match="no speech-to-text backend"):
        stt.get_transcriber()


def test_describe_names_the_backend_in_use(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk-test")
    assert "Groq" in describe()


# ------------------------------------------------------------------ the API path


def test_a_successful_transcription(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk-test")
    _transport(
        monkeypatch,
        lambda request: httpx.Response(200, json={"text": "  I rolled back the deploy.  "}),
    )
    result = transcribe(_wav(2.0))
    assert result.text == "I rolled back the deploy."
    assert result.seconds == 2.0
    assert "Groq" in result.backend


def test_an_http_error_becomes_a_typed_error(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk-test")
    _transport(monkeypatch, lambda request: httpx.Response(401, text="Unauthorized"))
    with pytest.raises(AudioError, match="HTTP 401"):
        transcribe(_wav())


def test_an_unreachable_host_becomes_a_typed_error(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk-test")

    def _explode(request):
        raise httpx.ConnectError("no route to host")

    _transport(monkeypatch, _explode)
    with pytest.raises(AudioError, match="unreachable"):
        transcribe(_wav())


def test_an_empty_transcript_is_reported_not_returned(monkeypatch):
    """Silence should say so, not submit an empty answer for scoring."""
    monkeypatch.setenv("GROQ_API_KEY", "gsk-test")
    _transport(monkeypatch, lambda request: httpx.Response(200, json={"text": "   "}))
    with pytest.raises(AudioError, match="empty transcript"):
        transcribe(_wav())


def test_the_key_is_sent_and_the_audio_is_multipart(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk-secret")
    seen: dict[str, object] = {}

    def _handler(request):
        seen["auth"] = request.headers.get("authorization")
        seen["type"] = request.headers.get("content-type", "")
        return httpx.Response(200, json={"text": "ok"})

    _transport(monkeypatch, _handler)
    transcribe(_wav())

    assert seen["auth"] == "Bearer gsk-secret"
    assert "multipart/form-data" in str(seen["type"])


# ------------------------------------------------------------------ guards


def test_an_empty_recording_is_refused_before_any_backend_is_chosen():
    with pytest.raises(AudioError, match="empty"):
        transcribe(b"")


def test_an_oversized_recording_is_refused_with_the_limit(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk-test")
    with pytest.raises(AudioError, match="the limit is 25 MB"):
        transcribe(b"x" * (26 * 1024 * 1024))


# ------------------------------------------------------------------ duration


def test_duration_comes_from_the_wav_header():
    assert wav_seconds(_wav(3.0)) == 3.0


def test_a_non_wav_payload_reports_no_duration_rather_than_guessing():
    assert wav_seconds(b"not audio at all") is None
