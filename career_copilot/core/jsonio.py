"""Getting a JSON object back out of a model reply.

Moved here from ``tools/_shared`` because it stopped being a tools concern. The
interview rubric needs it too, and importing it from the tools package created a
cycle: ``tools`` imports the interview tool, which imports the rubric, which
imported ``tools``. Anything used by two sibling packages belongs beneath both
of them, not inside one.

``tools/_shared`` still re-exports it, so nothing that already imported it from
there has to change.
"""

from __future__ import annotations

import json
from typing import Any

from career_copilot.core.errors import ToolError

__all__ = ["parse_json_object"]


def parse_json_object(raw: str, *, context: str) -> dict[str, Any]:
    """Extract the first JSON object from a model reply.

    Models wrap JSON in prose or fences more often than they should, so the
    braces are located rather than trusted. A failure here is a ToolError, not
    a KeyError three frames later.
    """
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end <= start:
        raise ToolError(f"{context}: model reply contained no JSON object")
    try:
        parsed = json.loads(raw[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ToolError(f"{context}: model reply was not valid JSON") from exc
    if not isinstance(parsed, dict):
        raise ToolError(f"{context}: model reply was not a JSON object")
    return dict(parsed)
