"""What the agent reports while it is still working.

A turn takes seconds, most of it retrieval. Without this the user gets a
spinner and has to trust that something is happening; with it they can watch
the agent pick a tool, search, and come back - which is also the part a
reviewer needs to see to believe the loop is real rather than asserted.

These are progress reports, not results. The turn's answer comes back from
`run_agent` as it always did; nothing here changes what a caller gets, and a
caller that passes no sink sees no difference at all.

The sink is called from whatever thread is running the turn. It must not
raise and must not block - the transport layer's job is to hand the event
straight to a queue and return.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel

__all__ = [
    "AgentEvent",
    "EventSink",
    "Phase",
    "RetrievalEvent",
    "StatusEvent",
    "ToolEvent",
    "ToolState",
    "Verdict",
    "emit",
]

#: What the agent is doing right now. Drives the status line in the client.
Phase = Literal["moderating", "thinking", "searching", "grading", "requerying", "answering"]

ToolState = Literal["started", "finished", "error"]

#: What the retrieval grader decided about the evidence it was given.
Verdict = Literal["sufficient", "weak", "none"]


class StatusEvent(BaseModel):
    type: Literal["status"] = "status"
    phase: Phase
    detail: str | None = None


class ToolEvent(BaseModel):
    type: Literal["tool"] = "tool"
    name: str
    state: ToolState


class RetrievalEvent(BaseModel):
    """One round of the retrieve-grade-requery loop.

    Emitted by the retrieval pipeline once the grader exists. Declared here
    now because the client already renders it, and a shape agreed in one
    place is cheaper than a shape discovered twice.
    """

    type: Literal["retrieval"] = "retrieval"
    round: int
    verdict: Verdict
    query: str
    sources: int


AgentEvent = StatusEvent | ToolEvent | RetrievalEvent

EventSink = Callable[[AgentEvent], None]


def emit(sink: EventSink | None, event: AgentEvent) -> None:
    """Report progress if anyone is listening.

    Deliberately does not catch: a sink that raises is a bug in the transport,
    and swallowing it here would turn a broken progress stream into a silent
    one. The contract above says what a sink may do.
    """
    if sink is not None:
        sink(event)
