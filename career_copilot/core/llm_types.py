"""Typed shapes for a model call.

Split out of ``core.llm`` so that ``core.usage`` can describe a chat result
without importing the client, and the client can import the budget check
without a cycle. Nothing here talks to a network.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

__all__ = ["ChatMessage", "ChatResult", "CostSource", "ToolCall"]

# OpenAI's message format is heterogeneous (system/user/assistant/tool all
# differ), so a plain dict is the pragmatic type here rather than a union.
ChatMessage = dict[str, Any]

# Where a recorded cost figure came from. "openrouter" is the real charge the
# provider reported; "estimated" is our own arithmetic from a price table that
# can be out of date; "unknown" means we have neither and the figure is 0.0.
CostSource = str


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: str  # raw JSON string; the caller parses and validates it


class ChatResult(BaseModel):
    """Typed response. Callers never touch the raw SDK object."""

    content: str | None
    tool_calls: list[ToolCall] = []
    model: str
    finish_reason: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: float
    generation_id: str | None = None  # OpenRouter: look up exact cost with this

    # The charge OpenRouter reported for this generation, in USD. None when the
    # provider did not return one - then, and only then, do we fall back to the
    # static price table. Never guess silently: `UsageRecord.cost_source` says
    # which of the two a stored figure came from.
    cost_usd: float | None = None
