"""The agent against real tools, a real database and a real index.

The unit tests for the loop stub `resolve`, so they prove the loop's control
flow and nothing about whether the tools it calls actually work. Here the tools
are the real ones: `search_jobs` hits SQLite, `search_knowledge_base` hits
Chroma. Only the model is scripted - which is the point, because a scripted
model lets us assert exactly which tool the loop chose and what came back.
"""

from __future__ import annotations

import pytest

from career_copilot.agent import loop as agent_loop
from career_copilot.agent import run_agent
from career_copilot.core.types import ApplicationStatus, Profile
from career_copilot.storage import jobs as repo
from career_copilot.tools.registry import AgentMode
from tests.helpers import ScriptedChat, make_chat_result, tool_call

pytestmark = pytest.mark.slow


@pytest.fixture()
def in_domain(monkeypatch):
    class _Analysis:
        intent = "kb_question"

    monkeypatch.setattr(agent_loop, "analyse_query", lambda *_a, **_k: _Analysis())


@pytest.fixture()
def seeded_jobs(isolated_settings):
    from career_copilot.storage.db import init_db

    init_db()
    devops = repo.upsert_job(
        source="test",
        title="Platform Engineer",
        company="Bosch",
        location="Stuttgart",
        description="Kubernetes, Terraform, GitLab CI.",
        profile=Profile.DEVOPS,
    )
    repo.upsert_job(
        source="test",
        title="Security Engineer",
        company="Continental",
        location="Regensburg",
        description="ISO/SAE 21434, TARA, UNECE R155.",
        profile=Profile.AUTOMOTIVE_CYBER,
    )
    return devops


def test_agent_answers_from_the_real_knowledge_base(indexed_kb, in_domain, monkeypatch):
    scripted = ScriptedChat(
        [
            make_chat_result(
                tool_calls=[tool_call("search_knowledge_base", {"question": "OOMKilled"})]
            ),
            make_chat_result("A container over its memory limit is OOMKilled [1]."),
        ]
    )
    monkeypatch.setattr(agent_loop, "chat", scripted)

    answer = run_agent("why would a pod be OOMKilled?", mode=AgentMode.CHAT)

    assert answer.steps[0].ok is True
    assert "kubernetes.md" in answer.steps[0].output
    assert answer.answer.startswith("A container")


def test_retrieved_text_reaches_the_model_wrapped_as_untrusted(indexed_kb, in_domain, monkeypatch):
    scripted = ScriptedChat(
        [
            make_chat_result(tool_calls=[tool_call("search_knowledge_base", {"question": "TARA"})]),
            make_chat_result("done"),
        ]
    )
    monkeypatch.setattr(agent_loop, "chat", scripted)

    run_agent("what is TARA?", mode=AgentMode.CHAT)

    tool_message = scripted.requests[1]["messages"][-1]
    assert tool_message["role"] == "tool"
    assert "untrusted data" in tool_message["content"]


def test_agent_searches_real_job_records(seeded_jobs, in_domain, monkeypatch):
    scripted = ScriptedChat(
        [
            make_chat_result(tool_calls=[tool_call("search_jobs", {"profile": "devops"})]),
            make_chat_result("One DevOps role: Platform Engineer at Bosch."),
        ]
    )
    monkeypatch.setattr(agent_loop, "chat", scripted)

    answer = run_agent("what devops roles have I saved?", mode=AgentMode.JOBS)

    assert answer.steps[0].ok is True
    assert f"id={seeded_jobs.id}" in answer.steps[0].output
    assert "Continental" not in answer.steps[0].output


def test_agent_writes_to_the_real_database(seeded_jobs, in_domain, monkeypatch):
    scripted = ScriptedChat(
        [
            make_chat_result(
                tool_calls=[
                    tool_call(
                        "set_application_status", {"job_id": seeded_jobs.id, "status": "applied"}
                    )
                ]
            ),
            make_chat_result("Marked as applied."),
        ]
    )
    monkeypatch.setattr(agent_loop, "chat", scripted)

    run_agent("I applied to the Bosch role", mode=AgentMode.JOBS)

    assert repo.funnel_counts()["applied"] == 1


def test_a_real_tool_failure_comes_back_as_a_step(seeded_jobs, in_domain, monkeypatch):
    """No stubbing of `resolve` here - the tool genuinely rejects the id."""
    scripted = ScriptedChat(
        [
            make_chat_result(
                tool_calls=[
                    tool_call(
                        "set_application_status", {"job_id": "not-a-real-id", "status": "applied"}
                    )
                ]
            ),
            make_chat_result("That job is not in the database."),
        ]
    )
    monkeypatch.setattr(agent_loop, "chat", scripted)

    answer = run_agent("mark job not-a-real-id as applied", mode=AgentMode.JOBS)

    assert answer.steps[0].ok is False
    assert repo.funnel_counts()["applied"] == 0
    assert answer.answer == "That job is not in the database."


def test_chat_mode_cannot_reach_a_writing_tool_even_against_a_real_database(
    seeded_jobs, in_domain, monkeypatch
):
    """The allowlist, exercised end to end rather than in isolation."""
    scripted = ScriptedChat(
        [
            make_chat_result(
                tool_calls=[
                    tool_call(
                        "set_application_status", {"job_id": seeded_jobs.id, "status": "offer"}
                    )
                ]
            ),
            make_chat_result("I cannot change applications in chat mode."),
        ]
    )
    monkeypatch.setattr(agent_loop, "chat", scripted)

    answer = run_agent("mark it as an offer", mode=AgentMode.CHAT)

    assert answer.steps[0].ok is False
    assert "not available" in answer.steps[0].output
    assert repo.funnel_counts()[str(ApplicationStatus.OFFER)] == 0
