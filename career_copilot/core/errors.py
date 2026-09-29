"""Typed exception hierarchy.

Every error carries a safe user-facing message, a full technical detail that is
logged but never rendered, and a correlation id linking the two.
"""

from __future__ import annotations

from uuid import uuid4

__all__ = [
    "AudioError",
    "BudgetExceededError",
    "ConfigError",
    "CopilotError",
    "DocumentError",
    "IngestionError",
    "LLMError",
    "RateLimitedError",
    "RetrievalError",
    "SecurityError",
    "ToolError",
    "ValidationError",
]


class CopilotError(Exception):
    """Base for all application errors.

    Args:
        detail: full technical description. Logged, never shown to the user.
        correlation_id: 8-char id shared between the UI message and the log line.
    """

    user_message: str = "Something went wrong."

    def __init__(self, detail: str, *, correlation_id: str | None = None) -> None:
        self.detail = detail
        self.correlation_id = correlation_id or uuid4().hex[:8]
        super().__init__(detail)


class ConfigError(CopilotError):
    user_message = "The application is not configured correctly."


class ValidationError(CopilotError):
    user_message = "That input isn't valid. Please check and try again."


class SecurityError(CopilotError):
    user_message = "That request was blocked for security reasons."


class LLMError(CopilotError):
    user_message = "The model is unavailable right now. Please try again."
    retryable: bool = True


class BudgetExceededError(LLMError):
    user_message = "The spending limit for this session has been reached."


class RateLimitedError(LLMError):
    user_message = "Too many requests. Retrying shortly."

    def __init__(
        self,
        detail: str,
        *,
        retry_after: float | None = None,
        correlation_id: str | None = None,
    ) -> None:
        self.retry_after = retry_after
        super().__init__(detail, correlation_id=correlation_id)


class RetrievalError(CopilotError):
    user_message = "I couldn't search the knowledge base."


class IngestionError(CopilotError):
    user_message = "A job source couldn't be updated."


class ToolError(CopilotError):
    user_message = "That action couldn't be completed."


class DocumentError(CopilotError):
    user_message = "The document couldn't be generated."


class AudioError(CopilotError):
    user_message = "I couldn't process the audio."
