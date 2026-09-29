import pytest

from career_copilot.core.errors import (
    BudgetExceededError,
    LLMError,
    RateLimitedError,
    ValidationError,
)
from career_copilot.core.retry import is_retryable, retry_policy

# sleep is injected as a no-op, so these run in microseconds instead of seconds.
instant = retry_policy(sleep=lambda _: None)


def test_retries_transient_failure_then_succeeds():
    calls = {"n": 0}

    @instant
    def flaky() -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise RateLimitedError("429 from upstream")
        return "ok"

    assert flaky() == "ok"
    assert calls["n"] == 3


def test_non_retryable_error_is_raised_immediately():
    calls = {"n": 0}

    @instant
    def bad_input() -> str:
        calls["n"] += 1
        raise ValidationError("empty input")

    with pytest.raises(ValidationError):
        bad_input()
    assert calls["n"] == 1, "validation errors must not be retried"


def test_budget_exceeded_is_never_retried():
    """Inherits from LLMError, so it would be retried without the explicit guard."""
    calls = {"n": 0}

    @instant
    def over_budget() -> str:
        calls["n"] += 1
        raise BudgetExceededError("session ceiling reached")

    with pytest.raises(BudgetExceededError):
        over_budget()
    assert calls["n"] == 1


def test_gives_up_after_max_attempts():
    calls = {"n": 0}
    policy = retry_policy(attempts=3, sleep=lambda _: None)

    @policy
    def always_fails() -> str:
        calls["n"] += 1
        raise RateLimitedError("429")

    with pytest.raises(RateLimitedError):
        always_fails()
    assert calls["n"] == 3


def test_retryable_flag_is_respected():
    """llm.py sets retryable=False on 4xx responses that are our own fault."""
    err = LLMError("client error 422")
    err.retryable = False  # type: ignore[attr-defined]
    assert is_retryable(err) is False
    assert is_retryable(LLMError("upstream 503")) is True


def test_rate_limited_carries_retry_after():
    err = RateLimitedError("429", retry_after=2.5)
    assert err.retry_after == 2.5
