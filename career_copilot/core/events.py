"""What the application reports while it is still working.

A turn takes seconds, most of it retrieval. Without this the user gets a
spinner and has to trust that something is happening; with it they can watch
the agent pick a tool, search, judge what came back and search again - which
is also the part a reviewer needs to see to believe the loop is real rather
than asserted.

These are progress reports, not results. Every function that emits them
returns exactly what it returned before, and a caller that installs no sink
sees no difference at all.

**Why an ambient sink.** The retrieval pipeline is called from inside a tool,
and a tool's arguments are chosen by the model - there is nowhere to thread a
callback through. So the sink is installed once for the turn and read from a
context variable, exactly as the session id already is in `core.session`. The
two solve the same problem for the same reason.

This lives in `core` rather than next to the agent because `rag` emits these
too, and `rag` must not depend on `agent`.

A sink is called from whatever thread is running the turn. It must not raise
and must not block - the transport layer's job is to hand the event straight
to a queue and return.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Literal

from pydantic import BaseModel

__all__ = [
    "AgentEvent",
    "DeltaEvent",
    "EventSink",
    "Phase",
    "RetrievalEvent",
    "StatusEvent",
    "ToolEvent",
    "ToolState",
    "Verdict",
    "current_sink",
    "emit",
    "use_sink",
]

#: What the application is doing right now. Drives the status line in the client.
Phase = Literal["moderating", "thinking", "searching", "grading", "requerying", "answering"]

ToolState = Literal["started", "finished", "error"]

#: What the retrieval grader decided about the evidence it was given.
Verdict = Literal["sufficient", "weak", "none"]


class StatusEvent(BaseModel):
    type: Literal["status"] = "status"
    phase: Phase
    detail: str | None = None


class DeltaEvent(BaseModel):
    """One piece of the answer, as the model produces it.

    The SSE layer already had a `token` event; it carried the whole answer in a
    single frame because nothing below it streamed. This is what fills it in.
    Deliberately just the text: the client appends, and anything cleverer would
    put rendering decisions inside the event vocabulary.
    """

    type: Literal["delta"] = "delta"
    text: str


class ToolEvent(BaseModel):
    type: Literal["tool"] = "tool"
    name: str
    state: ToolState


class RetrievalEvent(BaseModel):
    """One round of the retrieve-grade-requery loop.

    The round number is what makes a re-query visible: a second event with the
    same question but a different `query` is the agent saying "that was not
    good enough, let me ask differently".
    """

    type: Literal["retrieval"] = "retrieval"
    round: int
    verdict: Verdict
    query: str
    sources: int
    reason: str | None = None


AgentEvent = StatusEvent | ToolEvent | RetrievalEvent | DeltaEvent

EventSink = Callable[[AgentEvent], None]

_SINK: ContextVar[EventSink | None] = ContextVar("career_copilot_event_sink", default=None)


def current_sink() -> EventSink | None:
    """The sink installed for this turn, if any."""
    return _SINK.get()


@contextmanager
def use_sink(sink: EventSink | None) -> Iterator[None]:
    """Install a progress sink for everything called inside this block."""
    token = _SINK.set(sink)
    try:
        yield
    finally:
        _SINK.reset(token)


def emit(sink: EventSink | None, event: AgentEvent) -> None:
    """Report progress if anyone is listening.

    An explicit sink wins; otherwise the one installed for this turn is used.
    Pass `None` from code that has no callback of its own - which is most of
    it - and the ambient one still receives the event.

    Deliberately does not catch: a sink that raises is a bug in the transport,
    and swallowing it here would turn a broken progress stream into a silent
    one. The contract above says what a sink may do.
    """
    resolved = sink if sink is not None else _SINK.get()
    if resolved is not None:
        resolved(event)
