"""Every failure the client can see arrives in the same envelope.

The client branches on `code` and shows `message`. That only works if the
shape is identical whether the failure came from the agent, from Pydantic
rejecting a request, or from Starlette not finding a route - and identical
includes the spelling of the keys, which is the part that silently differs
when three layers each build their own body.
"""

from __future__ import annotations

import pytest

from career_copilot.api.errors import ApiError, status_and_code
from career_copilot.core.errors import (
    BudgetExceededError,
    CopilotError,
    LLMError,
    RateLimitedError,
    SecurityError,
    ToolError,
)


@pytest.mark.parametrize(
    ("exc", "status", "code"),
    [
        (BudgetExceededError("over"), 429, "budget_exhausted"),
        (RateLimitedError("slow down"), 429, "rate_limited"),
        (SecurityError("injection"), 400, "moderation_blocked"),
        (ToolError("not in this mode"), 400, "tool_not_permitted"),
        (LLMError("provider down"), 503, "upstream_unavailable"),
        (CopilotError("something"), 500, "internal_error"),
    ],
)
def test_each_error_maps_to_its_own_code(exc, status, code):
    assert status_and_code(exc) == (status, code)


def test_a_budget_error_is_not_swallowed_by_its_parent():
    """`BudgetExceededError` is an `LLMError`. Order in the mapping is what
    keeps "you have spent your limit" from reading as "the provider is down",
    which a user would answer by retrying - and paying for the retry."""
    assert status_and_code(BudgetExceededError("over"))[1] == "budget_exhausted"
    assert status_and_code(LLMError("down"))[1] == "upstream_unavailable"


def test_the_envelope_is_camel_case():
    body = ApiError(code="internal_error", message="No.", correlation_id="abc12345").model_dump(
        by_alias=True, exclude_none=True
    )

    assert body == {"code": "internal_error", "message": "No.", "correlationId": "abc12345"}


def test_a_missing_correlation_id_is_absent_rather_than_null():
    body = ApiError(code="not_found", message="Not Found").model_dump(
        by_alias=True, exclude_none=True
    )

    assert "correlationId" not in body


@pytest.mark.parametrize(
    ("path", "method", "payload"),
    [
        ("/api/nope", "get", None),
        ("/api/chat/stream", "post", {"threadId": "t1", "mode": "chat", "message": ""}),
    ],
)
def test_every_failure_has_a_code_and_a_message(client, path, method, payload):
    response = getattr(client, method)(path, **({"json": payload} if payload else {}))

    body = response.json()
    assert set(body) <= {"code", "message", "correlationId"}
    assert body["code"] and body["message"]


def test_the_envelope_never_carries_the_technical_detail(client):
    """`detail` is logged. The response gets the correlation id instead."""
    body = client.post(
        "/api/chat/stream", json={"threadId": "t1", "mode": "chat", "message": ""}
    ).json()

    assert "detail" not in body
