"""LangSmith tracing, off unless you ask for it.

Three things this module has to get right, and each one is a decision rather
than a default:

**A fresh clone must run without a LangSmith key.** Tracing is opt-in through
``CC_TRACING_ENABLED`` and stays off when the key is missing, so someone who
clones the repo and runs the tests never sees a warning, a retry or a stall.

**The decorators must be free when it is off.** ``@traced`` resolves to the
undecorated function the first time it is called, so a disabled build pays one
boolean check per function, not per call.

**Automatic instrumentation does not cover this codebase.** LangSmith traces
LangChain and LangGraph calls on its own, and ``core.llm.chat`` talks to the
OpenAI SDK directly - so none of the real work would appear. ``instrument``
wraps the client to produce the LLM leaves, and ``@traced`` on the agent loop,
the retrieval pipeline and each tool produces the tree they hang from.

Turn it on:

    CC_TRACING_ENABLED=true
    LANGSMITH_API_KEY=ls__...
    LANGSMITH_PROJECT=praxa        # optional, defaults to "praxa"
"""

from __future__ import annotations

import functools
import importlib.util
import os
from collections.abc import Callable
from typing import Any, Literal, TypeVar, cast

from career_copilot.core.errors import CopilotError
from career_copilot.core.logging import get_logger

__all__ = [
    "RunType",
    "add_run_metadata",
    "instrument",
    "reset_tracing",
    "traced",
    "tracing_active",
]

log = get_logger(__name__)

F = TypeVar("F", bound=Callable[..., Any])

# The kinds of step LangSmith renders. Spelled out rather than `str` so a typo
# is a type error here instead of a silently mis-rendered trace.
RunType = Literal["tool", "chain", "llm", "retriever", "embedding", "prompt", "parser"]

# Resolved on first use rather than at import: settings raise without an API
# key, and importing this module must never be the thing that fails.
_ACTIVE: bool | None = None


def _resolve() -> bool:
    """Decide once whether tracing runs, and configure the SDK if so."""
    from career_copilot.core.config import get_settings

    try:
        settings = get_settings()
    except CopilotError:
        return False  # unconfigured app; tracing is the least of its problems

    if not settings.tracing_enabled:
        return False

    key = settings.langsmith_api_key.get_secret_value()
    if not key:
        log.warning("CC_TRACING_ENABLED is set but LANGSMITH_API_KEY is empty - tracing is off")
        return False

    if importlib.util.find_spec("langsmith") is None:
        log.warning("CC_TRACING_ENABLED is set but langsmith is not installed - tracing is off")
        return False

    # The SDK is configured through the environment, which is its documented
    # contract. Settings stay the single source of truth; this copies them into
    # the shape the library reads.
    os.environ["LANGSMITH_TRACING"] = "true"
    os.environ["LANGSMITH_API_KEY"] = key
    os.environ["LANGSMITH_PROJECT"] = settings.langsmith_project
    if settings.langsmith_endpoint:
        os.environ["LANGSMITH_ENDPOINT"] = _checked_endpoint(settings.langsmith_endpoint)

    log.info("tracing enabled", extra={"project": settings.langsmith_project})
    return True


def _checked_endpoint(endpoint: str) -> str:
    """Warn about the mistake everyone makes with a regional workspace.

    The address you sign in at is the web app; the SDK needs the API host, which
    is the same name with "api." in front of it. Pointing the SDK at the web app
    fails at ingest time with a message that does not say why, so it is worth
    catching here.
    """
    host = endpoint.removeprefix("https://").removeprefix("http://").split("/")[0]
    if host.endswith("smith.langchain.com") and not host.startswith(("api.", "eu.api.")):
        log.warning(
            "LANGSMITH_ENDPOINT looks like the web address rather than the API host - "
            "traces will be rejected",
            extra={
                "endpoint": endpoint,
                "expected_shape": "https://<region.>api.smith.langchain.com",
            },
        )
    return endpoint


def tracing_active() -> bool:
    """Whether traces are being sent. Cached after the first call."""
    global _ACTIVE
    if _ACTIVE is None:
        _ACTIVE = _resolve()
    return _ACTIVE


def reset_tracing() -> None:
    """Forget the cached decision. For tests that change the environment."""
    global _ACTIVE
    _ACTIVE = None


def traced(name: str | None = None, *, run_type: RunType = "chain") -> Callable[[F], F]:
    """Record this function as a step in the trace.

    A no-op when tracing is off: the wrapper resolves to the original function
    on first call and stays that way, so a disabled build carries no per-call
    cost beyond one attribute lookup.

    Args:
        name: what the step is called in the trace. Defaults to the function's
            own name.
        run_type: "chain" for a step, "retriever" for a lookup, "tool" for a
            tool call. LangSmith renders each differently.
    """

    def decorate(fn: F) -> F:
        resolved: Callable[..., Any] | None = None

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            nonlocal resolved
            if resolved is None:
                resolved = _wrap(fn, name or fn.__name__, run_type)
            return resolved(*args, **kwargs)

        # The wrapper takes and returns exactly what `fn` does; `functools.wraps`
        # cannot express that to the type checker, so say it here instead of
        # silencing the error.
        return cast(F, wrapper)

    return decorate


def _wrap(fn: Callable[..., Any], name: str, run_type: RunType) -> Callable[..., Any]:
    if not tracing_active():
        return fn
    try:
        from langsmith import traceable
    except ImportError:
        return fn
    return traceable(name=name, run_type=run_type)(fn)


def instrument(client: Any) -> Any:
    """Return a client whose calls appear in the trace, or the client unchanged.

    Without this the trace would show the shape of a turn but none of its model
    calls, tokens or cost - which is most of what a trace is for.
    """
    if not tracing_active():
        return client
    try:
        from langsmith.wrappers import wrap_openai
    except ImportError:
        return client
    return wrap_openai(client)


def add_run_metadata(**fields: Any) -> None:
    """Attach fields to the step currently being traced.

    Used for the things you filter a trace list by - the mode, the session -
    which are not arguments to any one function. Silently does nothing when
    tracing is off or no step is open.
    """
    if not tracing_active():
        return
    try:
        from langsmith.run_helpers import get_current_run_tree
    except ImportError:
        return

    run = get_current_run_tree()
    if run is None:
        return
    try:
        run.extra.setdefault("metadata", {}).update(fields)
    except (AttributeError, TypeError):
        # Never let bookkeeping break the turn it is describing.
        log.debug("could not attach trace metadata")
