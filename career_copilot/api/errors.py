"""Turning a typed application error into a typed HTTP response.

Every failure the client can act on differently gets a different `code`. The UI
branches on that string, not on the status or the message text: "your spending
limit is reached" and "the model provider is down" both look like a failed
request, and a user who cannot tell them apart will retry the wrong one.

`detail` - the full technical description - is logged and never sent. The
correlation id is sent, so a screenshot of an error can be found in the log.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from career_copilot.api.schemas import Camel
from career_copilot.core.errors import (
    AudioError,
    BudgetExceededError,
    ConfigError,
    CopilotError,
    DocumentError,
    IngestionError,
    LLMError,
    RateLimitedError,
    RetrievalError,
    SecurityError,
    ToolError,
    ValidationError,
)
from career_copilot.core.logging import get_logger

__all__ = ["ApiError", "error_response", "install_error_handlers", "status_and_code"]

log = get_logger(__name__)


class ApiError(Camel):
    """The body of every non-2xx response under /api.

    camelCase like every other response, and via the same base class - an
    error body the client has to parse differently from a success body is an
    error body that gets parsed wrong on the day it matters.
    """

    code: str
    message: str
    correlation_id: str | None = None

    def as_response(self, status: int) -> JSONResponse:
        """`by_alias` is what makes it camelCase; `exclude_none` keeps an
        absent correlation id absent rather than explicitly null."""
        return JSONResponse(
            status_code=status,
            content=self.model_dump(by_alias=True, exclude_none=True),
        )


# Order matters: subclasses before their parents, because BudgetExceededError
# and RateLimitedError are both LLMError and would otherwise be swallowed by it.
_MAPPING: tuple[tuple[type[CopilotError], int, str], ...] = (
    (BudgetExceededError, 429, "budget_exhausted"),
    (RateLimitedError, 429, "rate_limited"),
    (SecurityError, 400, "moderation_blocked"),
    (ValidationError, 400, "invalid_request"),
    (RetrievalError, 502, "insufficient_evidence"),
    (ToolError, 400, "tool_not_permitted"),
    (DocumentError, 500, "internal_error"),
    (IngestionError, 500, "internal_error"),
    (AudioError, 503, "upstream_unavailable"),
    (LLMError, 503, "upstream_unavailable"),
    (ConfigError, 500, "internal_error"),
)


def status_and_code(exc: CopilotError) -> tuple[int, str]:
    """The HTTP status and stable code for one application error."""
    for error_type, status, code in _MAPPING:
        if isinstance(exc, error_type):
            return status, code
    return 500, "internal_error"


def error_response(exc: CopilotError) -> JSONResponse:
    """The body the client receives. Carries no technical detail."""
    status, code = status_and_code(exc)
    body = ApiError(code=code, message=exc.user_message, correlation_id=exc.correlation_id)
    return body.as_response(status)


async def _handle(request: Request, exc: Exception) -> JSONResponse:
    """Log the detail, send the safe message.

    Starlette types every handler against `Exception`; this one is registered
    for `CopilotError` alone, and anything else is a bug in the registration
    rather than a case to absorb quietly.
    """
    if not isinstance(exc, CopilotError):
        raise exc

    status, code = status_and_code(exc)
    log.warning(
        "request failed",
        extra={
            "path": request.url.path,
            "code": code,
            "status": status,
            "detail": exc.detail,
            "correlation_id": exc.correlation_id,
        },
    )
    return error_response(exc)


async def _handle_validation(request: Request, exc: Exception) -> JSONResponse:
    """A malformed request, in the same envelope as everything else.

    FastAPI's own 422 body is a list of Pydantic error dicts under `detail`.
    It is useful while developing and useless to a client that branches on
    `code`, so it is logged and replaced. The field paths are the detail here,
    and detail is not something a response carries.
    """
    log.info(
        "rejected a malformed request",
        extra={"path": request.url.path, "detail": str(exc)},
    )
    return ApiError(code="invalid_request", message="That request wasn't valid.").as_response(422)


async def _handle_http(request: Request, exc: Exception) -> JSONResponse:
    """Starlette's own errors - a 404, a 405 - given the same envelope."""
    if not isinstance(exc, StarletteHTTPException):
        raise exc

    code = "not_found" if exc.status_code == 404 else "invalid_request"
    return ApiError(code=code, message=str(exc.detail)).as_response(exc.status_code)


def install_error_handlers(app: FastAPI) -> None:
    """One response envelope for every failure the client can see."""
    app.add_exception_handler(CopilotError, _handle)
    app.add_exception_handler(RequestValidationError, _handle_validation)
    app.add_exception_handler(StarletteHTTPException, _handle_http)
