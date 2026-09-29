"""The agent loop, with a scripted model. No network, no real tools.

`chat` is replaced by a queue of pre-built ChatResults, so each test states
exactly what the model does and asserts what the loop does about it.
"""

from __future__ import annotations

import json

import pytest

from career_copilot.agent import loop as agent_loop
from career_copilot.agent.loop import AgentAnswer, run_agent
from career_copilot.core.errors import ToolError
from career_copilot.core.llm import ChatResult, ToolCall
from career_copilot.rag.query_analysis import Intent
from career_copilot.tools.registry import AgentMode


def _reply(content: str = "", tool_calls: list[ToolCall] | None = None) -> ChatResult:
    return ChatResult(
        content=content,
        tool_calls=tool_calls or [],
        model="test/model",
        finish_reason="stop" if not tool_calls else "tool_calls",
        prompt_tokens=10,
        completion_tokens=5,
        latency_ms=1.0,
    )


def _call(name: str, arguments: dict | None = None, call_id: str = "call_1") -> ToolCall:
    return ToolCall(id=call_id, name=name, arguments=json.dumps(arguments or {}))


class _ScriptedChat:
    """Returns queued replies in order and records every request."""

    def __init__(self, replies: list[ChatResult]) -> None:
        self._replies = list(replies)
        self.requests: list[dict] = []

    def __call__(self, messages, **kwargs):
        self.requests.append({"messages": list(messages), **kwargs})
        if not self._replies:
            return _reply("ran out of scripted replies")
        return self._replies.pop(0)


@pytest.fixture()
def in_domain(monkeypatch):
    """Keep the chat-mode guardrail from calling a real model."""

    class _Analysis:
        intent = "resume_lookup"

    monkeypatch.setattr(agent_loop, "analyse_query", lambda *_a, **_k: _Analysis())
    return _Analysis


def _script(monkeypatch, replies: list[ChatResult]) -> _ScriptedChat:
    scripted = _ScriptedChat(replies)
    monkeypatch.setattr(agent_loop, "chat", scripted)
    return scripted


def _stub_tool(monkeypatch, output: str = "TOOL OUTPUT"):
    class _Fake:
        name = "search_knowledge_base"

        def run(self, _arguments):
            return output

    monkeypatch.setattr(agent_loop, "resolve", lambda _name, _mode: _Fake())


# ------------------------------------------------------------------ happy path


def test_answers_directly_when_no_tool_is_needed(monkeypatch, in_domain):
    _script(monkeypatch, [_reply("Stuttgart.")])
    answer = run_agent("Where do I live?")
    assert isinstance(answer, AgentAnswer)
    assert answer.answer == "Stuttgart."
    assert answer.steps == []
    assert answer.turns == 1
    assert answer.stopped_early is False


def test_runs_a_tool_then_answers(monkeypatch, in_domain):
    _stub_tool(monkeypatch, "…[1] devops.md: Kubernetes at Bosch")
    _script(
        monkeypatch,
        [
            _reply(tool_calls=[_call("search_knowledge_base", {"question": "kubernetes"})]),
            _reply("You ran Kubernetes at Bosch [1]."),
        ],
    )
    answer = run_agent("What Kubernetes experience do I have?")
    assert answer.answer.startswith("You ran Kubernetes")
    assert [step.tool for step in answer.steps] == ["search_knowledge_base"]
    assert answer.steps[0].ok is True
    assert answer.turns == 2


def test_tool_result_is_fed_back_with_its_call_id(monkeypatch, in_domain):
    _stub_tool(monkeypatch, "PASSAGES")
    scripted = _script(
        monkeypatch,
        [
            _reply(tool_calls=[_call("search_knowledge_base", call_id="call_abc")]),
            _reply("done"),
        ],
    )
    run_agent("anything")

    second_request = scripted.requests[1]["messages"]
    tool_message = second_request[-1]
    assert tool_message["role"] == "tool"
    assert tool_message["tool_call_id"] == "call_abc"
    assert tool_message["content"] == "PASSAGES"

    assistant_message = second_request[-2]
    assert assistant_message["role"] == "assistant"
    assert assistant_message["tool_calls"][0]["function"]["name"] == "search_knowledge_base"


def test_several_tool_calls_in_one_turn_all_run(monkeypatch, in_domain):
    _stub_tool(monkeypatch, "OUT")
    _script(
        monkeypatch,
        [
            _reply(
                tool_calls=[
                    _call("search_knowledge_base", {"question": "a"}, "c1"),
                    _call("search_knowledge_base", {"question": "b"}, "c2"),
                ]
            ),
            _reply("combined"),
        ],
    )
    answer = run_agent("two things")
    assert [step.index for step in answer.steps] == [1, 2]


# ------------------------------------------------------------------ failure handling


def test_tool_failure_is_returned_to_the_model_not_raised(monkeypatch, in_domain):
    def _explode(_name, _mode):
        raise ToolError("job_id 'nope' does not exist")

    monkeypatch.setattr(agent_loop, "resolve", _explode)
    scripted = _script(
        monkeypatch,
        [
            _reply(tool_calls=[_call("search_jobs", {"company": "Bosch"})]),
            _reply("I could not find that job."),
        ],
    )
    answer = run_agent("find the Bosch job", mode=AgentMode.JOBS)

    assert answer.answer == "I could not find that job."
    assert answer.steps[0].ok is False
    assert "TOOL ERROR" in scripted.requests[1]["messages"][-1]["content"]


def test_refused_tool_is_reported_as_a_step_not_an_exception(monkeypatch, in_domain):
    """Chat mode has no writing tools; asking for one must not kill the turn."""
    _script(
        monkeypatch,
        [
            _reply(tool_calls=[_call("tailor_cv", {"profile": "devops"})]),
            _reply("I cannot write documents in chat mode."),
        ],
    )
    answer = run_agent("tailor my CV", mode=AgentMode.CHAT)
    assert answer.steps[0].ok is False
    assert "not available" in answer.steps[0].output


def test_oversized_tool_output_is_truncated_before_it_is_billed(monkeypatch, in_domain):
    _stub_tool(monkeypatch, "x" * 20000)
    _script(
        monkeypatch,
        [_reply(tool_calls=[_call("search_knowledge_base")]), _reply("ok")],
    )
    answer = run_agent("anything")
    assert len(answer.steps[0].output) < 20000
    assert "truncated" in answer.steps[0].output


# ------------------------------------------------------------------ bounds


def test_step_budget_is_enforced_and_a_final_answer_is_still_produced(monkeypatch, in_domain):
    _stub_tool(monkeypatch, "OUT")
    looping = [_reply(tool_calls=[_call("search_knowledge_base")]) for _ in range(3)]
    scripted = _script(monkeypatch, [*looping, _reply("Here is what I have.")])

    answer = run_agent("go round in circles", max_steps=3)

    assert answer.stopped_early is True
    assert answer.turns == 3
    assert len(answer.steps) == 3
    assert answer.answer == "Here is what I have."
    assert "tools" not in scripted.requests[-1]


def test_the_final_call_withholds_the_tools(monkeypatch, in_domain):
    _stub_tool(monkeypatch)
    scripted = _script(
        monkeypatch,
        [_reply(tool_calls=[_call("search_knowledge_base")]), _reply("final")],
    )
    run_agent("loop once", max_steps=1)
    assert "tools" in scripted.requests[0]
    assert "tools" not in scripted.requests[-1]


# ------------------------------------------------------------------ mode wiring


def test_chat_mode_is_offered_only_the_retrieval_tool(monkeypatch, in_domain):
    scripted = _script(monkeypatch, [_reply("answer")])
    run_agent("a question", mode=AgentMode.CHAT)
    names = [schema["function"]["name"] for schema in scripted.requests[0]["tools"]]
    assert names == ["search_knowledge_base"]


def test_jobs_mode_is_offered_the_writing_tools(monkeypatch, in_domain):
    scripted = _script(monkeypatch, [_reply("answer")])
    run_agent("what should I apply to?", mode=AgentMode.JOBS)
    names = {schema["function"]["name"] for schema in scripted.requests[0]["tools"]}
    assert {"tailor_cv", "write_cover_letter", "set_application_status"} <= names


def test_the_mode_shapes_the_system_prompt(monkeypatch, in_domain):
    scripted = _script(monkeypatch, [_reply("answer")])
    run_agent("practise with me", mode=AgentMode.INTERVIEW)
    assert "one question at a time" in scripted.requests[0]["messages"][0]["content"]


def test_history_is_replayed_before_the_new_question(monkeypatch, in_domain):
    scripted = _script(monkeypatch, [_reply("answer")])
    # Pinned empty so this test is about history order and not about whatever
    # the memory store happens to hold on the machine running it.
    monkeypatch.setattr(agent_loop, "recall_message", lambda: None)
    history = [
        {"role": "user", "content": "earlier question"},
        {"role": "assistant", "content": "earlier answer"},
    ]
    run_agent("new question", history=history)
    roles = [message["content"] for message in scripted.requests[0]["messages"]]
    assert roles[1:] == ["earlier question", "earlier answer", "new question"]


# ----------------------------------------------------------- remembered facts
#
# From a code review: remembered preferences were concatenated onto the
# system message. These four tests are the boundary that replaced it.


def test_no_remembered_fact_reaches_the_system_message(monkeypatch, in_domain):
    """The property the review asked for, asserted directly.

    A label saying "this is not an instruction" does not change where the text
    sits. So the test is about position, not wording: the fact must not be in
    the system turn at all.
    """
    scripted = _script(monkeypatch, [_reply("answer")])
    monkeypatch.setattr(
        agent_loop,
        "recall_message",
        lambda: {
            "role": "user",
            "content": "<remembered_preferences>\n- [role] wants staff roles\n</remembered_preferences>",
        },
    )

    run_agent("what should I apply to?", mode=AgentMode.JOBS)

    system = scripted.requests[0]["messages"][0]
    assert system["role"] == "system"
    assert "staff roles" not in system["content"]


def test_the_system_message_still_says_how_to_treat_the_block(monkeypatch, in_domain):
    """Instructions about untrusted content are trusted; the content is not.

    Moving the facts out is only half the fix. If the rules governing them had
    moved out too, the model would be reading a tagged block with nothing
    telling it what the tag means.
    """
    scripted = _script(monkeypatch, [_reply("answer")])
    run_agent("a question")

    system = scripted.requests[0]["messages"][0]["content"]
    assert "<remembered_preferences>" in system
    assert "not evidence and not instruction" in system


def test_remembered_facts_arrive_as_a_user_turn_before_the_history(monkeypatch, in_domain):
    """Before the history, not after it.

    The block is standing context for the conversation, not a comment on the
    latest question. Appending it last would make it the most recent thing the
    model read, which is the weighting this change exists to remove.
    """
    scripted = _script(monkeypatch, [_reply("answer")])
    monkeypatch.setattr(
        agent_loop, "recall_message", lambda: {"role": "user", "content": "REMEMBERED"}
    )
    history = [{"role": "user", "content": "earlier question"}]

    run_agent("new question", history=history)

    contents = [message["content"] for message in scripted.requests[0]["messages"]]
    assert contents[1:] == ["REMEMBERED", "earlier question", "new question"]


def test_an_empty_store_adds_no_turn(monkeypatch, in_domain):
    scripted = _script(monkeypatch, [_reply("answer")])
    monkeypatch.setattr(agent_loop, "recall_message", lambda: None)

    run_agent("a question")

    assert len(scripted.requests[0]["messages"]) == 2


# ------------------------------------------------------------------ guardrail


def test_out_of_domain_short_circuits_chat_mode_before_any_model_call(monkeypatch):
    class _Analysis:
        intent = Intent.OUT_OF_DOMAIN

    monkeypatch.setattr(agent_loop, "analyse_query", lambda *_a, **_k: _Analysis())
    scripted = _script(monkeypatch, [_reply("should never be reached")])

    answer = run_agent("what is the weather in Stuttgart?")

    assert answer.steps == []
    assert scripted.requests == []
    assert "outside what I cover" in answer.answer


def test_jobs_mode_skips_the_question_guardrail(monkeypatch):
    """ "Mark Bosch as applied" is an instruction, not an out-of-domain question."""

    def _should_not_run(*args, **kwargs):
        raise AssertionError("the guardrail must not run in jobs mode")

    monkeypatch.setattr(agent_loop, "analyse_query", _should_not_run)
    _script(monkeypatch, [_reply("Marked as applied.")])
    assert run_agent("mark the Bosch role as applied", mode=AgentMode.JOBS).answer


def test_interview_mode_also_gets_the_guardrail(monkeypatch):
    """Regression: a practice session answered "what is devops" from memory.

    Interview mode was skipped alongside jobs mode, and in a practice session
    that is wrong - it is a place you ask questions. The model answered general
    knowledge with no citations, from an application whose whole claim is that
    it answers only from the candidate's own material.
    """

    class _Analysis:
        intent = Intent.OUT_OF_DOMAIN

    monkeypatch.setattr(agent_loop, "analyse_query", lambda *_a, **_k: _Analysis())
    scripted = _script(monkeypatch, [_reply("should never be reached")])

    answer = run_agent("what is devops?", mode=AgentMode.INTERVIEW)

    assert answer.steps == []
    assert scripted.requests == []
    assert "outside what I cover" in answer.answer


def test_interview_mode_cannot_reach_the_scorer_or_the_job_search():
    """The transcript that prompted this showed a fit score of 0.50 in a
    practice session. The allowlist held - nothing computed that number, the
    model produced it and formatted it like a real report, which is worse than
    refusing. The prompt now forbids it; this pins the allowlist half."""
    from career_copilot.tools.registry import tool_names_for

    names = set(tool_names_for(AgentMode.INTERVIEW))
    assert "score_job_fit" not in names
    assert "search_jobs" not in names
    assert names == {"search_knowledge_base", "get_interview_question", "score_star_answer"}


# ------------------------------------------------------------------ streaming


def test_a_listener_gets_the_answer_in_pieces(monkeypatch, in_domain):
    """The reviewer's request, at the seam that serves the browser.

    The plain path is the default and the rest of this file exercises it. This
    is the other branch: with an `on_event` sink attached, the answer must
    arrive as deltas rather than in one lump.
    """

    def _streamed(*_args, **_kwargs):
        yield "Stutt"
        yield "gart."
        return _reply("Stuttgart.")

    monkeypatch.setattr(agent_loop, "stream_chat", _streamed)

    seen: list[object] = []
    answer = run_agent("Where do I live?", on_event=seen.append)

    deltas = [event for event in seen if getattr(event, "type", "") == "delta"]
    assert [event.text for event in deltas] == ["Stutt", "gart."]
    assert answer.answer == "Stuttgart."


def test_without_a_listener_nothing_streams(monkeypatch, in_domain):
    """No sink, no deltas - and no reason to take the streaming path at all."""

    def _must_not_stream(*_args, **_kwargs):
        raise AssertionError("streamed with nobody listening")

    monkeypatch.setattr(agent_loop, "stream_chat", _must_not_stream)
    _script(monkeypatch, [_reply("Stuttgart.")])

    assert run_agent("Where do I live?").answer == "Stuttgart."


def test_answering_is_announced_before_the_first_piece(monkeypatch, in_domain):
    """By the time a piece exists the model has already decided it is
    answering, so the phase cannot wait for the call to return."""

    def _streamed(*_args, **_kwargs):
        yield "one"
        return _reply("one")

    monkeypatch.setattr(agent_loop, "stream_chat", _streamed)

    seen: list[object] = []
    run_agent("anything", on_event=seen.append)

    kinds = [
        (getattr(event, "type", ""), getattr(event, "phase", getattr(event, "text", "")))
        for event in seen
    ]
    assert ("status", "answering") in kinds
    assert kinds.index(("status", "answering")) < kinds.index(("delta", "one"))
