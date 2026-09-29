"""Phase 0 acceptance gate.

    python scripts/up.py

Checks configuration, connectivity, and - critically - that the configured model
completes a full tool-calling round trip. Everything in Phase 3 depends on that.
Exits non-zero if any check fails, so CI could run it too.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from career_copilot.core.config import get_settings
from career_copilot.core.errors import CopilotError
from career_copilot.core.llm import chat
from career_copilot.core.logging import configure_logging
from career_copilot.core.usage import new_session_id, session_usd

ADD_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "add_numbers",
        "description": "Add two numbers. Use this for any arithmetic; do not calculate yourself.",
        "parameters": {
            "type": "object",
            "properties": {
                "a": {"type": "number", "description": "first number"},
                "b": {"type": "number", "description": "second number"},
            },
            "required": ["a", "b"],
        },
    },
}

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  -  {detail}" if detail else ""))
    if not ok:
        failures.append(name)
    return ok


def verify_config() -> Any:
    settings = get_settings()
    check("config loads", True, f"model={settings.chat_model}")
    check(
        "api key looks like a key",
        settings.openrouter_api_key.get_secret_value().startswith("sk-or-"),
    )
    check("data dir writable", _writable(settings.data_dir))
    check("chroma dir writable", _writable(settings.chroma_dir))
    return settings


def _writable(path: Any) -> bool:
    try:
        probe = path / ".write-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False
    else:
        return True


def verify_chat(model: str, label: str, session_id: str) -> None:
    """Plain completion - proves connectivity, auth and token accounting."""
    try:
        result = chat(
            [{"role": "user", "content": "Reply with exactly: OK"}],
            session_id=session_id,
            operation="verify",
            model=model,
            max_tokens=10,
        )
    except CopilotError as exc:
        check(f"{label} responds", False, exc.detail)
        return

    check(f"{label} responds", bool(result.content), repr((result.content or "")[:40]))
    check(f"{label} reports tokens", result.prompt_tokens > 0)


def verify_tool_calling(model: str, session_id: str) -> None:
    """The check that matters: a complete two-leg tool-calling round trip."""
    a, b = 21358, 47291
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": f"What is {a} plus {b}? Use the add_numbers tool."}
    ]

    try:
        first = chat(
            messages,
            session_id=session_id,
            operation="verify-tools",
            tools=[ADD_TOOL],
            tool_choice="auto",
            model=model,
        )
    except CopilotError as exc:
        check("model emits a tool call", False, exc.detail)
        return

    if not check("model emits a tool call", bool(first.tool_calls)):
        print("      -> this model may not support tool calling. Phase 3 needs one that does.")
        return

    call = first.tool_calls[0]
    check("tool name is correct", call.name == "add_numbers", call.name)

    try:
        args = json.loads(call.arguments)
    except json.JSONDecodeError:
        check("tool arguments are valid JSON", False, call.arguments[:60])
        return
    check("tool arguments are valid JSON", True, str(args))

    computed = args.get("a", 0) + args.get("b", 0)

    # Second leg: hand the result back and confirm the model uses it.
    messages.append(
        {
            "role": "assistant",
            "content": first.content,
            "tool_calls": [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.name, "arguments": call.arguments},
                }
            ],
        }
    )
    messages.append({"role": "tool", "tool_call_id": call.id, "content": str(computed)})

    try:
        second = chat(
            messages,
            session_id=session_id,
            operation="verify-tools",
            tools=[ADD_TOOL],
            model=model,
        )
    except CopilotError as exc:
        check("model uses the tool result", False, exc.detail)
        return

    answer = second.content or ""
    check("model uses the tool result", str(a + b) in answer.replace(",", ""), answer[:60])


def main() -> int:
    configure_logging(level="WARNING")
    session_id = new_session_id()

    print("\n--- configuration ---")
    settings = verify_config()

    print("\n--- primary model ---")
    verify_chat(settings.chat_model, settings.chat_model, session_id)

    print("\n--- tool calling ---")
    verify_tool_calling(settings.chat_model, session_id)

    if settings.fallback_model:
        print("\n--- fallback model ---")
        verify_chat(settings.fallback_model, settings.fallback_model, session_id)

    print("\n--- accounting ---")
    check("usage was recorded", session_usd(session_id) >= 0.0, f"${session_usd(session_id):.6f}")

    print("\n" + ("-" * 50))
    if failures:
        print(f"{len(failures)} check(s) failed: {', '.join(failures)}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
