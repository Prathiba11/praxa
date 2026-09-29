"""The allowlist is a security control, so it gets tested like one."""

from __future__ import annotations

import pytest

from career_copilot.core.errors import ToolError
from career_copilot.tools.registry import (
    ALL_TOOLS,
    AgentMode,
    resolve,
    schemas_for,
    tool_names_for,
    tools_for,
)

_WRITING_TOOLS = {"tailor_cv", "write_cover_letter", "set_application_status"}


def test_chat_mode_is_read_only():
    assert tool_names_for(AgentMode.CHAT) == ["search_knowledge_base"]


def test_interview_mode_cannot_write_anything():
    assert not _WRITING_TOOLS & set(tool_names_for(AgentMode.INTERVIEW))


def test_jobs_mode_owns_the_writing_tools():
    assert _WRITING_TOOLS.issubset(tool_names_for(AgentMode.JOBS))


@pytest.mark.parametrize("mode", list(AgentMode))
def test_every_mode_can_retrieve(mode):
    assert "search_knowledge_base" in tool_names_for(mode)


def test_resolve_refuses_a_tool_outside_the_mode():
    """The exact injection path: retrieved text names a tool the mode lacks."""
    with pytest.raises(ToolError) as excinfo:
        resolve("tailor_cv", AgentMode.CHAT)
    assert "not available" in str(excinfo.value.detail)


def test_resolve_refuses_an_invented_tool():
    with pytest.raises(ToolError):
        resolve("delete_everything", AgentMode.JOBS)


def test_resolve_returns_the_tool_when_allowed():
    assert resolve("search_jobs", AgentMode.JOBS).name == "search_jobs"


def test_schemas_match_the_allowlist_exactly():
    for mode in AgentMode:
        names = [schema["function"]["name"] for schema in schemas_for(mode)]
        assert sorted(names) == tool_names_for(mode)


def test_tool_names_are_unique():
    names = [tool.name for tool in ALL_TOOLS]
    assert len(names) == len(set(names))


def test_every_tool_declares_a_description_and_schema():
    for tool in ALL_TOOLS:
        schema = tool.openai_schema()
        assert len(schema["function"]["description"]) > 40
        assert schema["function"]["parameters"]["type"] == "object"


def test_tools_for_returns_tool_objects_in_a_stable_order():
    first = [tool.name for tool in tools_for(AgentMode.JOBS)]
    second = [tool.name for tool in tools_for(AgentMode.JOBS)]
    assert first == second
