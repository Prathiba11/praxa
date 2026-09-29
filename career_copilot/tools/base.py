"""The tool contract.

A tool is a typed callable the model is allowed to invoke. Three properties are
non-negotiable here, and each one exists because of a specific failure mode:

- **Arguments are a Pydantic model.** The model emits JSON; JSON from a language
  model is a guess. Validating before any code runs turns a hallucinated field
  into a clean ``ToolError`` instead of a half-finished database write.
- **Tools return a string.** Whatever a tool does, the model reads the result
  back as text. Tools never print and never mutate global UI state.
- **Failure is typed.** A tool that raises returns a ``ToolError`` carrying a
  ``user_message`` and a correlation id. The model never sees a traceback, and
  the user never sees a stack.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

from career_copilot.core.errors import CopilotError, ToolError
from career_copilot.core.logging import get_logger
from career_copilot.core.tracing import traced

__all__ = ["Tool", "ToolHandler"]

log = get_logger(__name__)

# The handler receives an instance of the tool's own ``args_model``. Python's
# type system cannot express "the model this particular Tool declares" without
# making Tool generic and every registry list heterogeneous, so the argument is
# deliberately Any and validation is enforced at runtime by ``run``.
ToolHandler = Callable[[Any], str]


@dataclass(frozen=True)
class Tool:
    """One callable exposed to the model."""

    name: str
    description: str
    args_model: type[BaseModel]
    handler: ToolHandler

    def openai_schema(self) -> dict[str, Any]:
        """The function-calling schema sent to the provider."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": " ".join(self.description.split()),
                "parameters": self.args_model.model_json_schema(),
            },
        }

    @traced("tool", run_type="tool")
    def run(self, arguments: str | Mapping[str, Any] | None = None) -> str:
        """Validate, execute, and return text the model can read."""
        payload = self._parse(arguments)

        try:
            args = self.args_model.model_validate(payload)
        except PydanticValidationError as exc:
            problems = "; ".join(
                f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
                for error in exc.errors()
            )
            raise ToolError(f"{self.name}: arguments failed validation: {problems}") from exc

        log.info("tool call", extra={"tool": self.name})
        try:
            result = self.handler(args)
        except CopilotError:
            # Already typed and already carries a user message - let it through
            # untouched so the correlation id stays the one that was logged.
            raise
        except Exception as exc:
            log.exception("tool raised", extra={"tool": self.name})
            raise ToolError(f"{self.name} failed: {type(exc).__name__}: {exc}") from exc

        log.info("tool ok", extra={"tool": self.name, "chars": len(result)})
        return result

    def _parse(self, arguments: str | Mapping[str, Any] | None) -> dict[str, Any]:
        if arguments is None:
            return {}
        if isinstance(arguments, Mapping):
            return dict(arguments)
        if not arguments.strip():
            return {}
        try:
            parsed = json.loads(arguments)
        except json.JSONDecodeError as exc:
            raise ToolError(f"{self.name}: arguments were not valid JSON") from exc
        if not isinstance(parsed, dict):
            raise ToolError(f"{self.name}: arguments must be a JSON object")
        return dict(parsed)
