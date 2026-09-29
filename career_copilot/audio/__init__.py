"""Audio input. One speech-to-text interface, local or hosted."""

from career_copilot.audio.stt import (
    AudioError,
    Transcriber,
    Transcript,
    available,
    describe,
    get_transcriber,
    transcribe,
    wav_seconds,
)

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
