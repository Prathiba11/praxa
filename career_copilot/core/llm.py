"""OpenRouter client - the only module that talks to an LLM.

Every SDK exception is mapped to a typed CopilotError here. Nothing raw, and
nothing containing the API key, base URL or request headers, escapes this file.

**The budget and the usage record live in this function, not in its callers.**
Previously each call site was responsible for calling ``check_budget`` before
and ``record_chat`` after, and most of them did neither: of eleven call sites in
the package, one checked the budget and two recorded nothing at all. A tool
invoked by the agent - fit scoring, CV tailoring, a cover letter - spent money
that no ceiling applied to and that no total ever saw. Putting both inside
``chat`` makes that structurally impossible rather than a rule to remember.
"""

from __future__ import annotations

import time
from collections.abc import Generator, Iterator
from functools import lru_cache
from typing import Any, cast

from langchain_openai import ChatOpenAI
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    NotFoundError,
    OpenAI,
    OpenAIError,
    PermissionDeniedError,
    RateLimitError,
    UnprocessableEntityError,
)

from career_copilot.core.config import Settings, get_settings
from career_copilot.core.errors import ConfigError, LLMError, RateLimitedError
from career_copilot.core.llm_types import ChatMessage, ChatResult, ToolCall
from career_copilot.core.logging import get_logger
from career_copilot.core.session import current_session_id
from career_copilot.core.tracing import instrument
from career_copilot.core.usage import check_budget, record_chat

__all__ = [
    "ChatMessage",
    "ChatResult",
    "ToolCall",
    "chat",
    "collect_stream",
    "get_chat_model",
    "get_client",
    "stream_chat",
]

log = get_logger(__name__)


def _sdk_http_module() -> Any | None:
    """The HTTP library the installed OpenAI SDK will accept a client from.

    There is more than one answer. Older SDKs check `isinstance(client,
    httpx.Client)`; newer ones have moved to `httpx2`, and handing over the
    wrong one is a `TypeError` on the first model call rather than anything
    subtle. Which is installed is not knowable from the source - it has to be
    asked at runtime, and the SDK's own base module is what does the checking,
    so it is the thing to ask.

    Returns None when the SDK's internals have moved again. That costs the
    connection settings below and nothing else: the caller then lets the SDK
    build its own client, which is exactly the behaviour this application had
    before those settings existed.
    """
    try:
        from openai import _base_client
    except ImportError:  # pragma: no cover - the SDK is a hard dependency
        return None

    for name in ("httpx", "httpx2"):
        module = getattr(_base_client, name, None)
        if module is not None:
            return module
    return None


def _transport_options(settings: Settings) -> dict[str, Any]:
    """How the HTTP connection to the provider is made and kept.

    Two decisions, both about the same failure: a turn makes several model
    calls with seconds of local CPU between them, and if each of those calls
    has to build a new connection, the cost of building one is paid over and
    over inside a single answer.

    `keepalive_expiry` keeps the connection alive across that gap - the
    default of five seconds is shorter than one reranking pass. `local_address`
    binds to IPv4, which is what stops the connection attempt from trying a
    dead IPv6 route first and waiting out its timeout; it is off unless asked
    for, because on an IPv6-only network it would be the bug rather than the
    fix.
    """
    return {
        "max_keepalive_connections": 10,
        "keepalive_expiry": settings.http_keepalive_seconds,
        "local_address": "0.0.0.0" if settings.force_ipv4 else None,
    }


def _http_client(settings: Settings) -> Any | None:
    """A client carrying those options, built from whichever library fits.

    None when the library cannot be identified - see `_sdk_http_module`.
    """
    module = _sdk_http_module()
    if module is None:
        log.warning(
            "could not identify the SDK's HTTP library - using its defaults, "
            "so CC_FORCE_IPV4 and CC_HTTP_KEEPALIVE_SECONDS will have no effect"
        )
        return None

    options = _transport_options(settings)
    limits = module.Limits(
        max_keepalive_connections=options["max_keepalive_connections"],
        keepalive_expiry=options["keepalive_expiry"],
    )
    return module.Client(
        timeout=settings.request_timeout,
        transport=module.HTTPTransport(limits=limits, local_address=options["local_address"]),
    )


@lru_cache(maxsize=1)
def get_client() -> OpenAI:
    settings = get_settings()
    headers = {}
    if settings.app_url:
        headers["HTTP-Referer"] = settings.app_url
    if settings.app_title:
        headers["X-Title"] = settings.app_title

    http_client = _http_client(settings)
    log.info(
        "building the model client",
        extra={
            "keepalive_s": settings.http_keepalive_seconds,
            "force_ipv4": settings.force_ipv4,
            "custom_transport": http_client is not None,
        },
    )
    # Supplying the client is the only way to reach the connection settings;
    # omitted when None, which leaves the SDK to build its own.
    optional: dict[str, Any] = {"http_client": http_client} if http_client else {}
    client = OpenAI(
        api_key=settings.openrouter_api_key.get_secret_value(),
        base_url=settings.openrouter_base_url,
        timeout=settings.request_timeout,
        max_retries=settings.max_retries,  # SDK-level retries, under our own policy
        default_headers=headers or None,
        **optional,
    )
    # `instrument` takes and returns an arbitrary client - it has no way to
    # know it was handed an OpenAI one - so the type has to be restated here.
    # It returns the same object untouched when tracing is off, and a wrapper
    # that forwards every call when it is on; either satisfies this signature.
    return cast(OpenAI, instrument(client))


def _retry_after_seconds(exc: APIStatusError) -> float | None:
    """Read the Retry-After header so we wait exactly as long as asked."""
    try:
        value = exc.response.headers.get("retry-after")
        return float(value) if value else None
    except (AttributeError, TypeError, ValueError):
        return None


def _not_retryable(detail: str) -> LLMError:
    err = LLMError(detail)
    err.retryable = False
    return err


def _reported_cost_usd(usage: object) -> float | None:
    """The charge OpenRouter reported for this generation, if it sent one.

    Asked for with ``extra_body={"usage": {"include": True}}``. The OpenAI SDK
    models the usage object against OpenAI's own schema, so the extra field
    arrives either as an attribute or in ``model_extra`` depending on SDK
    version - both are checked, and anything unparseable is treated as absent
    rather than as zero.
    """
    if usage is None:
        return None

    raw = getattr(usage, "cost", None)
    if raw is None:
        extra = getattr(usage, "model_extra", None)
        if isinstance(extra, dict):
            raw = extra.get("cost")
    if raw is None:
        return None

    try:
        return float(raw)
    except (TypeError, ValueError):
        log.warning("provider returned an unparseable cost", extra={"raw_cost": repr(raw)[:60]})
        return None


def _resolve_session(session_id: str | None) -> str:
    """The session this call belongs to.

    An explicit argument wins; otherwise the session opened by
    ``core.session.use_session``. Neither is a programming error, not a runtime
    condition to absorb: an unattributed call is exactly the hole this module
    exists to close.
    """
    resolved = session_id or current_session_id()
    if not resolved:
        raise ConfigError(
            "no session for this model call - pass session_id= or wrap the work "
            "in career_copilot.core.session.use_session(...)"
        )
    return resolved


def _create(client: OpenAI, **kwargs: Any) -> Any:
    """Send the request, mapping every SDK exception to a typed CopilotError.

    Extracted so `chat` and `stream_chat` cannot drift apart on error handling:
    a streamed call that mapped a 429 differently would be a second, quieter
    definition of what "rate limited" means here.
    """
    try:
        return client.chat.completions.create(**kwargs)

    # --- ORDER MATTERS: subclasses before their parents -----------------
    except RateLimitError as exc:  # 429, subclass of APIStatusError
        raise RateLimitedError(
            f"rate limited by upstream: {exc.status_code}",
            retry_after=_retry_after_seconds(exc),
        ) from exc
    except (AuthenticationError, PermissionDeniedError) as exc:  # 401, 403
        raise ConfigError(f"authentication rejected: HTTP {exc.status_code}") from exc
    except (BadRequestError, NotFoundError, UnprocessableEntityError) as exc:  # 400/404/422
        raise _not_retryable(f"invalid request: HTTP {exc.status_code}") from exc
    except APITimeoutError as exc:  # subclass of APIConnectionError - must come first
        raise LLMError("request timed out") from exc
    except APIConnectionError as exc:
        raise LLMError(f"connection failure: {type(exc).__name__}") from exc
    except APIStatusError as exc:  # anything else with a status, mostly 5xx
        if exc.status_code >= 500:
            raise LLMError(f"upstream error: HTTP {exc.status_code}") from exc
        raise _not_retryable(f"client error: HTTP {exc.status_code}") from exc
    except OpenAIError as exc:  # SDK-level catch-all
        raise LLMError(f"sdk error: {type(exc).__name__}") from exc


def chat(
    messages: list[ChatMessage],
    *,
    session_id: str | None = None,
    operation: str = "chat",
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | None = None,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> ChatResult:
    """Send a chat completion request and return a typed result.

    The spending ceiling is checked before the request goes out, and the usage
    is recorded after it returns. Both happen here so that no caller can skip
    them; `session_id` falls back to the ambient session when omitted.

    Args:
        session_id: who to bill and record against. Omit inside a
            ``use_session`` block; required otherwise.
        operation: what this call was for, stored on the usage record so the
            spend can be broken down later (``rag_answer``, ``score_job_fit``).

    Raises:
        BudgetExceededError: the session or monthly ceiling is already reached.
            Raised BEFORE the request, so nothing is spent.
        RateLimitedError: HTTP 429. Carries retry_after when the server sent it.
        LLMError: transport failure or upstream 5xx (retryable), or a 4xx we
            caused (retryable=False).
        ConfigError: bad key, malformed request, or no session in scope -
            retrying will not help.
    """
    resolved_session = _resolve_session(session_id)
    settings = get_settings()
    client = get_client()

    # Before the request, not after: a refused turn must cost nothing.
    check_budget(resolved_session)

    kwargs: dict[str, Any] = {
        "model": model or settings.chat_model,
        "messages": messages,
        "temperature": settings.temperature if temperature is None else temperature,
        "max_tokens": max_tokens or settings.max_tokens,
        # Ask OpenRouter to report what the generation actually cost, so the
        # stored figure is the real charge rather than our arithmetic against a
        # price table that goes stale.
        "extra_body": {"usage": {"include": True}},
    }
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = tool_choice or "auto"

    started = time.perf_counter()
    response = _create(client, **kwargs)
    latency_ms = (time.perf_counter() - started) * 1000

    choice = response.choices[0]
    raw_calls = choice.message.tool_calls or []
    usage = response.usage

    result = ChatResult(
        content=choice.message.content,
        tool_calls=[
            ToolCall(id=c.id, name=c.function.name, arguments=c.function.arguments)
            for c in raw_calls
        ],
        model=response.model,
        finish_reason=choice.finish_reason or "unknown",
        prompt_tokens=usage.prompt_tokens if usage else 0,
        completion_tokens=usage.completion_tokens if usage else 0,
        latency_ms=latency_ms,
        generation_id=response.id,
        cost_usd=_reported_cost_usd(usage),
    )

    entry = record_chat(result, session_id=resolved_session, operation=operation)

    log.info(
        "llm call complete",
        extra={
            "model": result.model,
            "operation": operation,
            "prompt_tokens": result.prompt_tokens,
            "completion_tokens": result.completion_tokens,
            "cost_usd": entry.cost_usd,
            "cost_source": entry.cost_source,
            "latency_ms": round(result.latency_ms),
            "tool_calls": len(result.tool_calls),
            "finish_reason": result.finish_reason,
        },
    )
    return result


def get_chat_model(*, model: str | None = None, temperature: float | None = None) -> ChatOpenAI:
    """LangChain wrapper over the same endpoint.

    Calls made through this object do NOT pass through ``chat`` and so are not
    budgeted or recorded here. The middleware layer is what meters them - see
    ``career_copilot.agent``. Nothing in the package uses this yet.
    """
    settings = get_settings()
    return ChatOpenAI(
        model=model or settings.chat_model,
        base_url=settings.openrouter_base_url,
        api_key=settings.openrouter_api_key,
        temperature=settings.temperature if temperature is None else temperature,
        max_completion_tokens=settings.max_tokens,
        timeout=settings.request_timeout,
        max_retries=settings.max_retries,
    )


def _absorb_tool_calls(deltas: Any, into: dict[int, dict[str, str]]) -> None:
    """Merge one chunk's tool-call fragments into the calls being assembled.

    A streamed tool call arrives in pieces keyed by `index`: the id and the
    function name usually in the first fragment, the arguments accumulated
    across later ones. Anything absent from a fragment is absent, not empty -
    overwriting with "" is how a call's name disappears halfway through.
    """
    for delta in deltas or []:
        index = getattr(delta, "index", 0) or 0
        call = into.setdefault(index, {"id": "", "name": "", "arguments": ""})
        if getattr(delta, "id", None):
            call["id"] = delta.id
        function = getattr(delta, "function", None)
        if function is None:
            continue
        if getattr(function, "name", None):
            call["name"] = function.name
        if getattr(function, "arguments", None):
            call["arguments"] += function.arguments


def collect_stream(stream: Iterator[str], on_delta: Any = None) -> ChatResult:
    """Drain a `stream_chat` generator and return its `ChatResult`."""
    while True:
        try:
            piece = next(stream)
        except StopIteration as stop:
            return cast(ChatResult, stop.value)
        if on_delta is not None:
            on_delta(piece)


def stream_chat(
    messages: list[ChatMessage],
    *,
    session_id: str | None = None,
    operation: str = "chat",
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | None = None,
) -> Generator[str, None, ChatResult]:
    """Stream one turn, yielding answer text as it arrives.

    Returns the finished `ChatResult` as the generator's return value; read it
    with `collect_stream` rather than the `StopIteration` dance at every site.

    Asked for in an earlier code review: the answer used to appear all at once
    after several seconds of nothing, and the SSE `token` event carried it in a
    single frame. The pipe was always built for this - the event type was chosen
    for it - and this is the half that was missing.

    **A separate function rather than a flag on `chat`.** `chat` is the single
    door to the model and the budget check and usage record live inside it; all
    thirteen callers depend on that. Adding a branch would put the guarantee on
    one side of an `if`. This duplicates none of it: the budget is checked here
    the same way, the errors go through the same `_create`, and the same
    `record_chat` runs at the end.

    **Tools are accepted, because the answer comes from a tool-capable call.**
    The agent asks with tools attached and only learns it has an answer when the
    reply carries no tool calls - by which point, without this, the whole text
    has already arrived. So the stream handles both, which means reassembling
    tool calls from fragments: the id in one chunk, the name in another, the
    arguments split across several. The alternative was a second model call per
    turn, charging the user twice for one answer.

    **Usage arrives last.** `stream_options.include_usage` asks the provider to
    send a final chunk carrying the token counts, and OpenRouter's `usage`
    extra adds the real cost to it. Without that flag a streamed call reports
    nothing and the ledger silently under-counts - which is the failure this
    function most had to avoid, because the ledger is the thing `chat` exists
    to protect.

    Raises:
        The same typed errors as `chat`, at the same points.
    """
    resolved_session = _resolve_session(session_id)
    settings = get_settings()
    client = get_client()

    # Before the request, not after: a refused turn must cost nothing.
    check_budget(resolved_session)

    started = time.perf_counter()
    stream = _create(
        client,
        model=model or settings.chat_model,
        messages=messages,
        temperature=settings.temperature if temperature is None else temperature,
        max_tokens=max_tokens or settings.max_tokens,
        stream=True,
        stream_options={"include_usage": True},
        extra_body={"usage": {"include": True}},
        **({"tools": tools, "tool_choice": tool_choice or "auto"} if tools else {}),
    )

    pieces: list[str] = []
    partial_calls: dict[int, dict[str, str]] = {}
    usage = None
    finish_reason = "unknown"
    used_model = model or settings.chat_model
    generation_id = None

    for chunk in stream:
        # The usage chunk carries no choices, and a choices chunk carries no
        # usage. Reading either unconditionally is how one of them gets lost.
        if getattr(chunk, "usage", None):
            usage = chunk.usage
        if getattr(chunk, "id", None):
            generation_id = chunk.id
        if getattr(chunk, "model", None):
            used_model = chunk.model

        choices = getattr(chunk, "choices", None) or []
        if not choices:
            continue
        choice = choices[0]
        if choice.finish_reason:
            finish_reason = choice.finish_reason
        _absorb_tool_calls(getattr(choice.delta, "tool_calls", None), partial_calls)

        piece = getattr(choice.delta, "content", None)
        if piece:
            pieces.append(piece)
            yield piece

    result = ChatResult(
        content="".join(pieces),
        tool_calls=[
            ToolCall(id=call["id"], name=call["name"], arguments=call["arguments"])
            for _index, call in sorted(partial_calls.items())
            if call["name"]
        ],
        model=used_model,
        finish_reason=finish_reason,
        prompt_tokens=usage.prompt_tokens if usage else 0,
        completion_tokens=usage.completion_tokens if usage else 0,
        latency_ms=(time.perf_counter() - started) * 1000,
        generation_id=generation_id,
        cost_usd=_reported_cost_usd(usage),
    )

    if usage is None:
        # Not fatal, but the ledger is now wrong for this turn and saying so is
        # the difference between a known gap and a quiet one.
        log.warning(
            "streamed call reported no usage - this turn is not counted",
            extra={"operation": operation, "model": used_model},
        )

    entry = record_chat(result, session_id=resolved_session, operation=operation)
    log.info(
        "llm stream complete",
        extra={
            "model": result.model,
            "operation": operation,
            "prompt_tokens": result.prompt_tokens,
            "completion_tokens": result.completion_tokens,
            "cost_usd": entry.cost_usd,
            "cost_source": entry.cost_source,
            "latency_ms": round(result.latency_ms),
            "finish_reason": result.finish_reason,
            "tool_calls": len(result.tool_calls),
        },
    )
    return result
