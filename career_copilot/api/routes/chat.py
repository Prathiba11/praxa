"""One chat turn, streamed as server-sent events.

**Why a stream at all.** A turn takes seconds and spends most of them in
retrieval. Streaming is not about the text arriving a word at a time - it is
about the agent's decisions being visible while they are being made, because
a trace shown after the fact is indistinguishable from a trace invented after
the fact.

**What is streamed.** Progress events as they happen - which phase, which tool,
which retrieval round - and the answer itself, in pieces, as the model writes
it. That last part was a placeholder for a long time: the `token` event existed
but carried the whole answer in a single frame, because nothing below it
streamed. `core.llm.stream_chat` is what filled it in. The old comment promised
that turning it on later
changes this file and nothing in the client.

**Why a thread.** `run_agent` is synchronous and spends its time waiting on the
network. Called directly from the event loop it would block every other
request, so it runs in a worker thread and reports back through a queue that
the generator drains. The queue is the only thing crossing the boundary, and it
is written to with `call_soon_threadsafe`.

**What happens on a failure mid-stream.** The status line said 200 before the
first byte was written, so there is no status left to fail with. A failure
after that point becomes an `error` event carrying the same code an ordinary
error response would have carried, and the stream then closes normally.

**What happens when the client goes away.** The generator stops being drained
and the turn keeps running to completion in its thread. It cannot be cancelled
mid-tool without leaving half-written state, and it must still be billed -
money was spent whether or not anyone is listening.

**What happens after the answer.** Memory extraction, and only then. The user
has their answer and the `done` frame has gone out before it starts, so it adds
nothing to the time they wait; it runs in a thread, and if it fails they never
find out. A memory feature that makes every answer slower is one people turn
off.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from career_copilot.agent.loop import AgentAnswer, run_agent
from career_copilot.api import threads
from career_copilot.api.errors import status_and_code
from career_copilot.api.schemas import ChatRequest, DoneEvent, ErrorEvent, TokenEvent, TurnUsage
from career_copilot.core.config import get_settings
from career_copilot.core.errors import CopilotError
from career_copilot.core.events import AgentEvent, DeltaEvent, use_sink
from career_copilot.core.logging import get_logger
from career_copilot.core.session import use_session
from career_copilot.core.usage import session_totals
from career_copilot.memory.extract import remember_turn
from career_copilot.tools.registry import AgentMode

__all__ = ["router"]

log = get_logger(__name__)

router = APIRouter(tags=["chat"])

# Proxies love to buffer text/event-stream into uselessness. These say not to.
_STREAM_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def _frame(event: BaseModel) -> str:
    """One SSE frame. `by_alias` is what makes the client see camelCase."""
    return f"data: {event.model_dump_json(by_alias=True)}\n\n"


def _raw_frame(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload)}\n\n"


async def _turn_frames(payload: ChatRequest) -> AsyncIterator[str]:
    """Run one turn, yielding frames as it goes."""
    thread = threads.get(payload.thread_id)
    settings = get_settings()
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[AgentEvent | None] = asyncio.Queue()

    def sink(event: AgentEvent) -> None:
        """Called from the worker thread. Hands over and returns immediately."""
        try:
            loop.call_soon_threadsafe(queue.put_nowait, event)
        except RuntimeError:
            # The loop has closed: the client disconnected and the response
            # was torn down. The turn still runs to the end and is still
            # billed - it simply has nobody left to report progress to.
            log.debug("progress event dropped, no listener", extra={"event": event.type})

    def work() -> AgentAnswer:
        # One turn at a time per thread: two would interleave their messages
        # and make the before/after usage snapshot meaningless.
        with thread.lock:
            history = thread.history()
            try:
                # Installed for the whole turn, not just the agent loop. The
                # retrieval grader runs inside a tool, and a tool's arguments
                # are chosen by the model - there is nowhere to pass a callback
                # through. `use_sink` is how its rounds reach this stream.
                with use_sink(sink):
                    answer = run_agent(
                        payload.message,
                        mode=AgentMode(payload.mode),
                        session_id=payload.thread_id,
                        history=history,
                        on_event=sink,
                    )
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)
            thread.record(payload.message, answer.answer)
            return answer

    before = session_totals(payload.thread_id)
    task = asyncio.create_task(asyncio.to_thread(work))

    # The client already appends `token` frames (`draftRef.current += text`),
    # so a delta goes out as a `token` and the wire protocol does not change -
    # it goes from one frame to many, which is what this event type was always
    # for.
    streamed = False
    while True:
        event = await queue.get()
        if event is None:
            break
        if isinstance(event, DeltaEvent):
            streamed = True
            yield _frame(TokenEvent(text=event.text))
            continue
        yield _frame(event)

    try:
        answer = await task
    except CopilotError as exc:
        _, code = status_and_code(exc)
        log.warning(
            "chat turn failed mid-stream",
            extra={
                "thread_id": payload.thread_id,
                "code": code,
                "detail": exc.detail,
                "correlation_id": exc.correlation_id,
            },
        )
        yield _frame(
            ErrorEvent(code=code, message=exc.user_message, correlation_id=exc.correlation_id)
        )
        return
    except Exception:
        # Not a CopilotError, so it is a bug rather than a handled condition.
        # It still has to leave the stream in a state the client understands.
        log.exception("chat turn crashed", extra={"thread_id": payload.thread_id})
        yield _frame(
            ErrorEvent(code="internal_error", message="Something went wrong on this turn.")
        )
        return

    # Only when nothing streamed. Sending it again after the deltas would
    # double the answer on screen, which is the obvious way to get this wrong.
    if not streamed:
        yield _frame(TokenEvent(text=answer.answer))

    spent = session_totals(payload.thread_id).since(before)
    yield _frame(
        DoneEvent(
            message_id=uuid4().hex,
            usage=TurnUsage(
                prompt_tokens=spent.prompt_tokens,
                completion_tokens=spent.completion_tokens,
                cost_usd=spent.cost_usd,
                cost_source=spent.cost_source,
                model=settings.chat_model,
                latency_ms=answer.latency_ms,
            ),
        )
    )

    # Only now. The answer is delivered, the bill is reported, and the user is
    # already reading - so this costs them nothing and is allowed to fail.
    await asyncio.to_thread(_remember, payload.thread_id, payload.message, answer.answer)


def _remember(thread_id: str, question: str, answer: str) -> None:
    """Extract and store what the turn revealed. Never raises.

    Billed to the same session as the turn it came from, so the cost of
    remembering shows up next to the cost of answering rather than nowhere.
    """
    try:
        with use_session(thread_id):
            remember_turn(question, answer, session_id=thread_id)
    except Exception:
        # Already-answered turn. Nothing here is allowed to surface.
        log.exception("memory extraction failed", extra={"thread_id": thread_id})


async def _frames(payload: ChatRequest) -> AsyncIterator[str]:
    """The generator handed to Starlette.

    A failure before the turn starts - configuration, mostly - still arrives
    after the 200, because the response has already been returned by the time
    Starlette pulls the first frame. So it is reported the same way.
    """
    try:
        async for frame in _turn_frames(payload):
            yield frame
    except CopilotError as exc:
        _, code = status_and_code(exc)
        log.warning(
            "chat stream could not start",
            extra={"code": code, "detail": exc.detail, "correlation_id": exc.correlation_id},
        )
        yield _frame(
            ErrorEvent(code=code, message=exc.user_message, correlation_id=exc.correlation_id)
        )
    finally:
        # A terminator the client can see. Without it a stream that ends
        # because the process died looks exactly like one that finished.
        yield _raw_frame({"type": "end"})


@router.post("/chat/stream")
async def chat_stream(payload: ChatRequest) -> StreamingResponse:
    """Stream one turn. Always 200 - failures are events, not statuses."""
    return StreamingResponse(
        _frames(payload),
        media_type="text/event-stream",
        headers=_STREAM_HEADERS,
    )
