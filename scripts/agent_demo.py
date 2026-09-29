"""Drive the agent from the terminal.

    python scripts/agent_demo.py --mode jobs "score the pasted role against my devops CV"
    python scripts/agent_demo.py --mode chat --trace "what ISO 21434 work have I done?"

Useful before the jobs UI exists, and useful afterwards: the trace shows the
tool calls with nothing rendered on top of them.
"""

from __future__ import annotations

import argparse
import sys

from career_copilot.agent import run_agent
from career_copilot.core.errors import CopilotError
from career_copilot.core.logging import configure_logging
from career_copilot.core.security import mask_pii, validate_user_input
from career_copilot.core.usage import new_session_id, session_usd
from career_copilot.storage.db import init_db
from career_copilot.tools.registry import AgentMode


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one agent turn.")
    parser.add_argument("question", help="What to ask.")
    parser.add_argument(
        "--mode",
        choices=[str(mode) for mode in AgentMode],
        default=str(AgentMode.CHAT),
        help="Which tool allowlist to use.",
    )
    parser.add_argument("--trace", action="store_true", help="Show each tool call.")
    parser.add_argument("--max-steps", type=int, default=6)
    return parser.parse_args(argv)


def _run(args: argparse.Namespace) -> int:
    configure_logging()
    init_db()
    session_id = new_session_id()

    clean = validate_user_input(args.question)
    masked = mask_pii(clean)
    if masked.found:
        print(f"Masked before sending: {masked.found}\n")

    answer = run_agent(
        masked.text,
        mode=AgentMode(args.mode),
        session_id=session_id,
        max_steps=args.max_steps,
    )

    if args.trace:
        print(f"--- {len(answer.steps)} tool step(s), {answer.turns} model turn(s) ---")
        for step in answer.steps:
            marker = "ok " if step.ok else "ERR"
            print(
                f"[{step.index}] {marker} {step.tool}({step.arguments})  {step.latency_ms:.0f} ms"
            )
            print("    " + step.output[:300].replace("\n", "\n    "))
        if answer.stopped_early:
            print("--- step budget exhausted; answered without further tools ---")
        print()

    print(answer.answer)
    print(f"\n[{answer.latency_ms:.0f} ms · ${session_usd(session_id):.4f}]")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        return _run(args)
    except CopilotError as exc:
        print(f"{exc.user_message}   ·   reference: {exc.correlation_id}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
