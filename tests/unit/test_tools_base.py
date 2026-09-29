"""The tool contract: validate before executing, and never leak a traceback."""

from __future__ import annotations

import pytest
from pydantic import BaseModel, Field

from career_copilot.core.errors import ToolError
from career_copilot.tools.base import Tool


class _Args(BaseModel):
    name: str = Field(min_length=1)
    count: int = Field(default=1, ge=1, le=5)


def _handler(args: _Args) -> str:
    return f"{args.name} x{args.count}"


_TOOL = Tool(
    name="demo",
    description="  A   demo   tool.  ",
    args_model=_Args,
    handler=_handler,
)


def test_schema_has_the_shape_the_provider_expects():
    schema = _TOOL.openai_schema()
    assert schema["type"] == "function"
    assert schema["function"]["name"] == "demo"
    assert schema["function"]["description"] == "A demo tool."
    assert "name" in schema["function"]["parameters"]["properties"]


def test_runs_from_a_json_string():
    assert _TOOL.run('{"name": "cv", "count": 2}') == "cv x2"


def test_runs_from_a_mapping():
    assert _TOOL.run({"name": "cv"}) == "cv x1"


def test_defaults_apply_when_argument_omitted():
    assert _TOOL.run('{"name": "cv"}').endswith("x1")


def test_malformed_json_is_a_tool_error():
    with pytest.raises(ToolError) as excinfo:
        _TOOL.run("{not json")
    assert "valid JSON" in str(excinfo.value.detail)


def test_json_array_is_rejected():
    with pytest.raises(ToolError):
        _TOOL.run("[1, 2, 3]")


def test_missing_required_field_is_a_tool_error_not_a_crash():
    with pytest.raises(ToolError) as excinfo:
        _TOOL.run("{}")
    assert "validation" in str(excinfo.value.detail).lower()


def test_out_of_range_value_is_rejected_before_the_handler_runs():
    calls: list[str] = []

    def _spy(args: _Args) -> str:
        calls.append(args.name)
        return "ran"

    tool = Tool(name="spy", description="d", args_model=_Args, handler=_spy)
    with pytest.raises(ToolError):
        tool.run('{"name": "cv", "count": 99}')
    assert calls == []


def test_handler_exception_becomes_a_tool_error():
    def _boom(_args: _Args) -> str:
        raise RuntimeError("disk on fire")

    tool = Tool(name="boom", description="d", args_model=_Args, handler=_boom)
    with pytest.raises(ToolError) as excinfo:
        tool.run('{"name": "cv"}')
    assert "boom failed" in str(excinfo.value.detail)
    assert isinstance(excinfo.value.__cause__, RuntimeError)


def test_typed_errors_pass_through_unwrapped():
    original = ToolError("already typed")

    def _raise(_args: _Args) -> str:
        raise original

    tool = Tool(name="passthrough", description="d", args_model=_Args, handler=_raise)
    with pytest.raises(ToolError) as excinfo:
        tool.run('{"name": "cv"}')
    assert excinfo.value is original


def test_empty_arguments_are_allowed_when_the_model_has_no_required_fields():
    class _Empty(BaseModel):
        pass

    tool = Tool(name="empty", description="d", args_model=_Empty, handler=lambda _a: "ok")
    assert tool.run(None) == "ok"
    assert tool.run("") == "ok"
