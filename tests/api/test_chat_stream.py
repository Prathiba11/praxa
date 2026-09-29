"""The streamed chat turn.

What is under test is the wire: which frames arrive, in what order, in what
spelling, and what happens when the turn fails after the 200 has gone out. The
agent itself is stubbed, because a test that needed a real model to prove that
an SSE frame is well-formed would prove neither.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from career_copilot.agent.loop import AgentAnswer
from career_copilot.api.routes import chat as chat_route
from career_copilot.api.schemas import ChatRequest
from career_copilot.core import usage as usage_module
from career_copilot.core.errors import BudgetExceededError, SecurityError
from career_copilot.core.events import StatusEvent, ToolEvent
from tests.api.conftest import sse_events

THREAD = "thread-1"


def _post(client, message="what have I done with Kubernetes?", mode="chat", thread=THREAD):
    return client.post(
        "/api/chat/stream",
        json={"threadId": thread, "mode": mode, "message": message},
    )


def _kinds(events):
    return [event["type"] for event in events]


@pytest.fixture()
def scripted_agent(monkeypatch):
    """A stand-in agent that reports progress and bills for it.

    It spends through the real usage log, so the `done` frame's numbers are
    produced the same way a real turn's would be.
    """
    seen: dict[str, object] = {}

    def fake_run_agent(question, *, mode, session_id, history=None, on_event=None, **_):
        seen["question"] = question
        seen["mode"] = str(mode)
        seen["history"] = list(history or [])
        if on_event is not None:
            on_event(StatusEvent(phase="thinking"))
            on_event(ToolEvent(name="search_knowledge_base", state="started"))
            on_event(ToolEvent(name="search_knowledge_base", state="finished"))
            on_event(StatusEvent(phase="answering"))
        usage_module.record(
            session_id=session_id,
            operation="agent_chat",
            model="openai/gpt-4o-mini",
            prompt_tokens=1000,
            completion_tokens=100,
        )
        return AgentAnswer(answer="You ran a cluster. [1]", mode=str(mode), latency_ms=42.0)

    monkeypatch.setattr(chat_route, "run_agent", fake_run_agent)
    return seen


# ---------------------------------------------------------------- happy path


def test_the_turn_streams_progress_then_the_answer(client, scripted_agent):
    response = _post(client)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")

    events = sse_events(response.text)
    assert _kinds(events) == [
        "status",
        "tool",
        "tool",
        "status",
        "token",
        "done",
        "end",
    ]


def test_progress_arrives_before_the_answer_not_with_it(client, scripted_agent):
    """The whole point of the stream. If the trace only lands with the answer,
    a spinner would have done the same job."""
    events = sse_events(_post(client).text)
    kinds = _kinds(events)

    assert kinds.index("tool") < kinds.index("token")


def test_frames_are_camel_case(client, scripted_agent):
    done = next(e for e in sse_events(_post(client).text) if e["type"] == "done")

    assert "messageId" in done
    assert "promptTokens" in done["usage"]
    assert "message_id" not in done


def test_the_answer_is_carried_by_a_token_event(client, scripted_agent):
    token = next(e for e in sse_events(_post(client).text) if e["type"] == "token")

    assert token["text"] == "You ran a cluster. [1]"


def test_the_message_is_stripped_before_it_reaches_the_agent(client, scripted_agent):
    _post(client, message="   spaces around me   ")

    assert scripted_agent["question"] == "spaces around me"


def test_the_mode_selects_the_toolset(client, scripted_agent):
    _post(client, mode="jobs")

    assert scripted_agent["mode"] == "jobs"


# --------------------------------------------------------------------- usage


def test_done_reports_what_this_turn_cost_not_what_the_thread_has(client, scripted_agent):
    """Two turns, and the second must not report the first one's spend again."""
    _post(client)
    second = sse_events(_post(client, message="and Terraform?").text)

    done = next(e for e in second if e["type"] == "done")
    assert done["usage"]["promptTokens"] == 1000
    assert done["usage"]["completionTokens"] == 100
    assert done["usage"]["costSource"] == "estimated"


def test_the_thread_accumulates_what_the_turns_spent(client, scripted_agent):
    _post(client)
    _post(client, message="and Terraform?")

    body = client.get("/api/usage", params={"threadId": THREAD}).json()
    assert body["sessionTokens"] == 2200


# ------------------------------------------------------------------- history


def test_the_first_turn_has_no_history(client, scripted_agent):
    _post(client)

    assert scripted_agent["history"] == []


def test_a_later_turn_sees_the_earlier_exchange(client, scripted_agent):
    _post(client, message="first question")
    _post(client, message="second question")

    assert scripted_agent["history"] == [
        {"role": "user", "content": "first question"},
        {"role": "assistant", "content": "You ran a cluster. [1]"},
    ]


def test_threads_do_not_see_each_other(client, scripted_agent):
    _post(client, message="mine", thread="thread-1")
    _post(client, message="theirs", thread="thread-2")

    assert scripted_agent["history"] == []


# -------------------------------------------------------------------- errors


@pytest.mark.parametrize(
    ("raised", "expected_code"),
    [
        (BudgetExceededError("session spend over limit"), "budget_exhausted"),
        (SecurityError("prompt injection in a fetched posting"), "moderation_blocked"),
    ],
)
def test_a_failure_mid_turn_becomes_an_error_event(client, monkeypatch, raised, expected_code):
    """There is no status code left to fail with once the stream is open."""

    def failing(*_args, **_kwargs):
        raise raised

    monkeypatch.setattr(chat_route, "run_agent", failing)

    response = _post(client)
    assert response.status_code == 200

    events = sse_events(response.text)
    error = next(e for e in events if e["type"] == "error")
    assert error["code"] == expected_code
    assert error["correlationId"]
    assert _kinds(events)[-1] == "end"


def test_an_error_event_carries_no_technical_detail(client, monkeypatch):
    def failing(*_args, **_kwargs):
        raise BudgetExceededError("session spend $1.0413 >= limit $1.00")

    monkeypatch.setattr(chat_route, "run_agent", failing)

    error = next(e for e in sse_events(_post(client).text) if e["type"] == "error")

    assert "1.0413" not in error["message"]
    assert error["message"] == BudgetExceededError.user_message


def test_a_bug_in_the_turn_still_closes_the_stream(client, monkeypatch):
    """An unexpected exception must not leave the client waiting forever."""

    def crashing(*_args, **_kwargs):
        raise RuntimeError("someone forgot a None check")

    monkeypatch.setattr(chat_route, "run_agent", crashing)

    events = sse_events(_post(client).text)

    assert next(e for e in events if e["type"] == "error")["code"] == "internal_error"
    assert _kinds(events)[-1] == "end"


def test_a_crash_does_not_leak_the_exception_text(client, monkeypatch):
    def crashing(*_args, **_kwargs):
        raise RuntimeError("/home/prathiba/data/cv_real.docx not found")

    monkeypatch.setattr(chat_route, "run_agent", crashing)

    error = next(e for e in sse_events(_post(client).text) if e["type"] == "error")

    assert "cv_real.docx" not in error["message"]


# ---------------------------------------------------------------- validation


@pytest.mark.parametrize(
    "payload",
    [
        {"threadId": "t1", "mode": "chat", "message": ""},
        {"threadId": "t1", "mode": "chat", "message": "   "},
        {"threadId": "t1", "mode": "hacking", "message": "hi"},
        {"threadId": "", "mode": "chat", "message": "hi"},
        {"threadId": "../../etc/passwd", "mode": "chat", "message": "hi"},
        {"mode": "chat", "message": "hi"},
    ],
)
def test_a_malformed_request_is_refused_before_anything_is_spent(client, payload):
    response = client.post("/api/chat/stream", json=payload)

    assert response.status_code == 422
    assert response.json()["code"] == "invalid_request"


def test_a_rejected_request_never_reaches_the_agent(client, monkeypatch):
    called = []
    monkeypatch.setattr(chat_route, "run_agent", lambda *a, **k: called.append(1))

    client.post("/api/chat/stream", json={"threadId": "t1", "mode": "chat", "message": ""})

    assert called == []


# ------------------------------------------------------------------- memory


def test_the_finished_turn_is_handed_to_the_extractor(client, scripted_agent, monkeypatch):
    """Memory is filled by turns, and this is the seam where that happens.

    Both halves of the turn go across, billed to the thread that produced
    them - an extraction recorded against nothing would be spend with no
    session to explain it.
    """
    seen: dict[str, object] = {}

    def fake_remember_turn(question, answer, *, session_id=None):
        seen.update(question=question, answer=answer, session_id=session_id)
        return 1

    monkeypatch.setattr(chat_route, "remember_turn", fake_remember_turn)
    _post(client, message="I only want remote roles")

    assert seen == {
        "question": "I only want remote roles",
        "answer": "You ran a cluster. [1]",
        "session_id": THREAD,
    }


def test_extraction_runs_after_the_answer_has_gone_out(client, scripted_agent, monkeypatch):
    """The ordering is the whole design, so it is asserted rather than assumed.

    By the time the extractor is called the `done` frame is already written.
    A memory feature that makes every answer slower is one people turn off.

    The generator is drained directly rather than through the test client,
    because what is being asserted is the order in which this code does two
    things - and a buffering HTTP client between them would decide that.
    """
    order: list[str] = []

    def fake_remember_turn(*_args, **_kwargs):
        order.append("remembered")
        return 0

    monkeypatch.setattr(chat_route, "remember_turn", fake_remember_turn)
    payload = ChatRequest.model_validate({"threadId": THREAD, "mode": "chat", "message": "hello"})

    async def drain() -> None:
        async for frame in chat_route._turn_frames(payload):
            order.append(json.loads(frame.removeprefix("data: "))["type"])

    asyncio.run(drain())

    assert order[-1] == "remembered"
    assert order.index("token") < order.index("done") < order.index("remembered")


def test_an_extractor_that_fails_does_not_spoil_the_answer(client, scripted_agent, monkeypatch):
    """The user already has their answer. Nothing after it may take it away."""

    def _explode(*_args, **_kwargs):
        raise RuntimeError("extractor exploded")

    monkeypatch.setattr(chat_route, "remember_turn", _explode)

    events = sse_events(_post(client).text)

    assert _kinds(events)[-2:] == ["done", "end"]
    assert next(e for e in events if e["type"] == "token")["text"] == "You ran a cluster. [1]"
