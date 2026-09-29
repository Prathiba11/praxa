"""Which session the work happening right now belongs to.

Model calls are made three or four levels below the code that knows the session
id: a tool is called by the agent loop, is handed its arguments by the model,
and its signature is fixed by the schema the model sees. Threading a session id
through those signatures is not possible, and the previous approach - an
optional ``session_id`` that callers could simply omit - meant a call with no
session was silently unbudgeted and unrecorded.

A context variable solves it without touching any tool signature: whoever starts
a turn opens ``use_session(...)`` once, and every model call underneath it,
however deeply nested, is attributed to that session.

Context variables are per-task, not global: two concurrent FastAPI requests each
see their own value, and a value set inside an ``asyncio`` task does not leak to
its siblings.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

__all__ = ["current_session_id", "use_session"]

_SESSION_ID: ContextVar[str | None] = ContextVar("career_copilot_session_id", default=None)


def current_session_id() -> str | None:
    """The session this code is running for, or None outside a session."""
    return _SESSION_ID.get()


@contextmanager
def use_session(session_id: str) -> Iterator[str]:
    """Attribute every model call in this block to ``session_id``.

    Restores the previous value on exit, so nesting is safe and an exception
    cannot leave a stale session id behind for the next turn.
    """
    token = _SESSION_ID.set(session_id)
    try:
        yield session_id
    finally:
        _SESSION_ID.reset(token)
