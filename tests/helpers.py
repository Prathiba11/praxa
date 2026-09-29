"""Test doubles and constants shared across the suites.

Kept out of `conftest.py` on purpose: `conftest` is for fixtures pytest injects,
and importing from another module's conftest is a habit that stops working the
moment the directory layout changes.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Sequence
from pathlib import Path

from career_copilot.core.llm import ChatResult, ToolCall

__all__ = [
    "REPO_ROOT",
    "HashingEmbedder",
    "ScriptedChat",
    "make_chat_result",
    "tool_call",
]

REPO_ROOT = Path(__file__).resolve().parents[1]

_TOKEN = re.compile(r"\w+", re.UNICODE)


class HashingEmbedder:
    """Deterministic bag-of-words vectors.

    Not a good embedder - it has no notion of meaning, only of shared tokens.
    That is exactly what makes it useful here: identical input gives identical
    output across processes and runs, and lexical overlap still outranks none,
    so retrieval assertions remain meaningful. ``hashlib`` rather than the
    built-in ``hash()`` because the latter is salted per process.
    """

    model_name = "test/hashing-embedder"
    dim = 96

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * self.dim
        for token in _TOKEN.findall(text.lower()):
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=4).digest()
            vector[int.from_bytes(digest, "big") % self.dim] += 1.0
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]

    def embed_documents(self, texts: list[str]) -> list[Sequence[float]]:
        return [self._vector(text) for text in texts]

    def embed_query(self, text: str) -> Sequence[float]:
        return self._vector(text)


def make_chat_result(content: str = "", tool_calls: list[ToolCall] | None = None) -> ChatResult:
    """A ChatResult with the boilerplate filled in."""
    return ChatResult(
        content=content,
        tool_calls=tool_calls or [],
        model="test/model",
        finish_reason="tool_calls" if tool_calls else "stop",
        prompt_tokens=10,
        completion_tokens=5,
        latency_ms=1.0,
    )


def tool_call(name: str, arguments: dict | None = None, call_id: str = "call_1") -> ToolCall:
    import json

    return ToolCall(id=call_id, name=name, arguments=json.dumps(arguments or {}))


class ScriptedChat:
    """Stands in for `chat`: returns queued replies and records every request.

    Recording the requests is half the value - it is how a test asserts which
    tools were offered, what came back from one, and that the final call
    withheld the tool schemas.
    """

    def __init__(self, replies: list[ChatResult]) -> None:
        self._replies = list(replies)
        self.requests: list[dict] = []

    def __call__(self, messages, **kwargs):
        self.requests.append({"messages": list(messages), **kwargs})
        if not self._replies:
            return make_chat_result("no further scripted replies")
        return self._replies.pop(0)
