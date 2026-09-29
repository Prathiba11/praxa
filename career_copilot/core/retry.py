"""Retry policy - which failures are worth retrying, and how long to wait.

Retrying a 401 spams a bad key forever. Retrying a 429 without jitter makes
parallel callers re-collide. Both distinctions are deliberate here.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from tenacity import (
    RetryCallState,
    before_sleep_log,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

from career_copilot.core.errors import (
    BudgetExceededError,
    IngestionError,
    LLMError,
    RateLimitedError,
)

__all__ = ["RETRYABLE_STATUS", "is_retryable", "retry_policy", "with_retry"]

# Transient by nature. Everything else (401, 403, 404, 422) is our bug, not theirs.
RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})

MAX_ATTEMPTS = 4
MAX_WAIT_SECONDS = 30.0

_log = logging.getLogger(__name__)


def is_retryable(exc: BaseException) -> bool:
    """Our own spend ceiling is never retryable - waiting will not add budget."""
    if isinstance(exc, BudgetExceededError):
        return False
    if not isinstance(exc, RateLimitedError | LLMError | IngestionError):
        return False
    # llm.py sets retryable=False on 4xx responses that are our fault.
    return bool(getattr(exc, "retryable", True))


def _wait(state: RetryCallState) -> float:
    """Honour Retry-After when the server sent one; otherwise back off with jitter."""
    exc = state.outcome.exception() if state.outcome else None
    retry_after = getattr(exc, "retry_after", None)
    if isinstance(retry_after, int | float) and retry_after > 0:
        return min(float(retry_after), MAX_WAIT_SECONDS)
    return float(wait_exponential_jitter(initial=1, max=MAX_WAIT_SECONDS)(state))


def retry_policy(
    *,
    attempts: int = MAX_ATTEMPTS,
    sleep: Callable[[float], Any] | None = None,
) -> Callable[..., Any]:
    """Build the decorator. `sleep` is injectable so tests run instantly."""
    kwargs: dict[str, Any] = {
        "retry": retry_if_exception(is_retryable),
        "wait": _wait,
        "stop": stop_after_attempt(attempts),
        "before_sleep": before_sleep_log(_log, logging.WARNING),
        "reraise": True,
    }
    if sleep is not None:
        kwargs["sleep"] = sleep
    policy: Callable[..., Any] = retry(**kwargs)
    return policy


with_retry = retry_policy()
