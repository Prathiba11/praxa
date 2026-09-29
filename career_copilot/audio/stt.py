"""Speech to text, behind one interface with two backends.

OpenRouter routes chat models and nothing else, so audio needs its own path.
There are two sensible ones and they suit different machines, which is why this
is an adapter rather than a function:

- **Local** (`faster-whisper`, CPU): no key, no cost, nothing leaves the machine.
  On a two-core box expect roughly 15-25 seconds for a one-minute answer - the
  same constraint that made reranking the bottleneck earlier in this project.
- **API** (Groq or OpenAI, whichever key is present): a second or two, a few
  cents an hour, and the audio leaves the machine.

Selection is automatic: a key in the environment wins, otherwise local, and if
neither is available the caller is told plainly rather than handed an exception
mid-interview. `describe()` exists so the UI can say which one is in use, because
"why is this slow" should be answerable by looking at the screen.

Deliberately not in `core.config`: `GROQ_API_KEY` and `OPENAI_API_KEY` are
optional third-party credentials that the rest of the app has no opinion about,
and putting them in Settings would imply the app needs them. The env-var read is
confined to this module.
"""

from __future__ import annotations

import importlib.util
import io
import os
import wave
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Protocol, runtime_checkable

import httpx

from career_copilot.core.errors import CopilotError
from career_copilot.core.logging import get_logger

__all__ = [
    "AudioError",
    "Transcriber",
    "Transcript",
    "available",
    "describe",
    "get_transcriber",
    "transcribe",
    "wav_seconds",
]

log = get_logger(__name__)

LOCAL_MODEL = "base"  # tiny is noticeably worse on technical vocabulary; small is 3x slower
_API_TIMEOUT_SECONDS = 120.0
_MAX_AUDIO_BYTES = 25 * 1024 * 1024  # both APIs reject more than this

_GROQ = (
    "GROQ_API_KEY",
    "https://api.groq.com/openai/v1/audio/transcriptions",
    "whisper-large-v3-turbo",
)
_OPENAI = ("OPENAI_API_KEY", "https://api.openai.com/v1/audio/transcriptions", "whisper-1")


class AudioError(CopilotError):
    user_message = "That recording could not be transcribed."


@dataclass(frozen=True)
class Transcript:
    text: str
    backend: str
    seconds: float | None = None


@runtime_checkable
class Transcriber(Protocol):
    """What the page depends on. Both backends satisfy it; so can a test double."""

    name: str

    def transcribe(self, audio: bytes) -> Transcript: ...


def wav_seconds(audio: bytes) -> float | None:
    """Duration from the WAV header, without decoding the audio.

    `st.audio_input` produces WAV, and the answer's length is worth recording:
    a 20-second answer and a three-minute one are different performances even
    when they score the same. Returns None for anything not readable as WAV
    rather than guessing.
    """
    try:
        with wave.open(io.BytesIO(audio)) as handle:
            frames = handle.getnframes()
            rate = handle.getframerate()
    except (wave.Error, EOFError):
        return None
    return round(frames / rate, 1) if rate else None


class _ApiTranscriber:
    """Groq or OpenAI. Both speak the same multipart endpoint."""

    def __init__(self, key: str, url: str, model: str, label: str) -> None:
        self._key = key
        self._url = url
        self._model = model
        self.name = label

    def transcribe(self, audio: bytes) -> Transcript:
        try:
            response = httpx.post(
                self._url,
                headers={"Authorization": f"Bearer {self._key}"},
                files={"file": ("answer.wav", audio, "audio/wav")},
                data={"model": self._model, "response_format": "json"},
                timeout=_API_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPStatusError as exc:
            # The status is the useful part; the body is often an HTML error page.
            raise AudioError(
                f"{self.name} refused the recording: HTTP {exc.response.status_code}"
            ) from exc
        except httpx.HTTPError as exc:
            raise AudioError(f"{self.name} was unreachable: {type(exc).__name__}") from exc

        text = str(payload.get("text", "")).strip()
        if not text:
            raise AudioError(f"{self.name} returned an empty transcript")
        return Transcript(text=text, backend=self.name, seconds=wav_seconds(audio))


class _LocalTranscriber:
    """faster-whisper on the CPU."""

    name = f"faster-whisper ({LOCAL_MODEL}, local)"

    def transcribe(self, audio: bytes) -> Transcript:
        segments, info = _local_model().transcribe(io.BytesIO(audio), beam_size=1)
        text = " ".join(segment.text.strip() for segment in segments).strip()
        if not text:
            raise AudioError("nothing recognisable in that recording")
        return Transcript(
            text=text,
            backend=self.name,
            seconds=round(float(info.duration), 1) if info.duration else wav_seconds(audio),
        )


@lru_cache(maxsize=1)
def _local_model() -> Any:
    """One model instance per process. Loading it costs seconds; doing that per
    answer would make the local backend unusable rather than merely slow.

    The import is here, not at module scope: faster-whisper pulls in ctranslate2
    and downloads a model on first use, and the app has to start on a machine
    that has neither. `available()` is what callers check instead of importing.
    """
    from faster_whisper import WhisperModel

    log.info("loading local speech model", extra={"model": LOCAL_MODEL})
    return WhisperModel(LOCAL_MODEL, device="cpu", compute_type="int8")


def _api_backend() -> _ApiTranscriber | None:
    for env_name, url, model in (_GROQ, _OPENAI):
        key = os.environ.get(env_name, "").strip()
        if key:
            label = "Groq" if env_name == _GROQ[0] else "OpenAI"
            return _ApiTranscriber(key, url, model, f"{label} {model}")
    return None


def available() -> bool:
    """Whether anything can transcribe on this machine, checked without loading
    a model or making a request."""
    return _api_backend() is not None or importlib.util.find_spec("faster_whisper") is not None


def describe() -> str:
    """One line for the UI. Says which backend and what to expect from it."""
    api = _api_backend()
    if api is not None:
        return f"{api.name} - about a second per answer."
    if importlib.util.find_spec("faster_whisper") is not None:
        return (
            f"{_LocalTranscriber.name} - free and private, but 15-25 seconds for a "
            f"one-minute answer on a slow machine."
        )
    return (
        "No speech backend. Install faster-whisper for local transcription, or set "
        "GROQ_API_KEY or OPENAI_API_KEY for a fast hosted one."
    )


def get_transcriber() -> Transcriber:
    """The backend to use. A key wins; otherwise local; otherwise a clear refusal."""
    api = _api_backend()
    if api is not None:
        return api
    if importlib.util.find_spec("faster_whisper") is not None:
        return _LocalTranscriber()
    raise AudioError(
        "no speech-to-text backend is available: install faster-whisper, or set "
        "GROQ_API_KEY or OPENAI_API_KEY"
    )


def transcribe(audio: bytes) -> Transcript:
    """Turn a recording into text. Raises AudioError for anything recoverable."""
    if not audio:
        raise AudioError("the recording was empty")
    if len(audio) > _MAX_AUDIO_BYTES:
        raise AudioError(
            f"that recording is {len(audio) // (1024 * 1024)} MB; the limit is "
            f"{_MAX_AUDIO_BYTES // (1024 * 1024)} MB. Answer in under a few minutes."
        )

    transcriber = get_transcriber()
    result = transcriber.transcribe(audio)
    log.info(
        "audio transcribed",
        extra={"backend": result.backend, "words": len(result.text.split())},
    )
    return result
