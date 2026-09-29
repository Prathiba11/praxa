"""Prove that every configured model actually answers.

    python scripts/check_models.py

The problem this solves: a model id that the provider does not serve fails with
a 404, and several places in this application are built to **fail open** when a
model call fails. That is right - a broken grader must not stop an answer being
given - but it means a wrong model id is invisible. The feature does not break;
it quietly stops existing, and the only evidence is one WARNING line in a log
nobody is reading.

That is exactly what happened here: `CC_GRADER_MODEL` pointed at a model the
account could not reach, so the retrieval grader and the memory extractor both
404'd on every single turn, for days, while the application went on answering
questions perfectly well without them.

Each configured model gets one request for one token. The whole run costs a
fraction of a cent and tells you which of them are real.
"""

from __future__ import annotations

import sys
import time

from career_copilot.core.config import get_settings
from career_copilot.core.errors import CopilotError
from career_copilot.core.llm import chat
from career_copilot.core.logging import configure_logging
from career_copilot.core.usage import new_session_id

#: One token, no tools, nothing to parse. We are asking "does this id resolve",
#: not "is this model any good".
_PROMPT = [{"role": "user", "content": "ping"}]


def _say(text: str = "") -> None:
    """Print, flushed.

    The application logs to stderr and this script prints to stdout. Those are
    two streams with different buffering, so without an explicit flush the
    result lines arrive out of order with the log lines they belong to - or,
    on a fast run, not until the process exits. A diagnostic whose output
    cannot be trusted to be in order is not much of a diagnostic.
    """
    print(text, flush=True)


def _check(label: str, model: str, session_id: str) -> bool:
    """One model, one call. Returns whether it answered."""
    _say(f"  {label:<10} {model}")
    started = time.perf_counter()
    try:
        chat(_PROMPT, session_id=session_id, operation="check_models", model=model, max_tokens=1)
    except CopilotError as exc:
        elapsed = (time.perf_counter() - started) * 1000
        _say(f"  {'':<10} FAILED after {elapsed:.0f} ms - {exc.detail}")
        if "404" in exc.detail:
            # By far the commonest cause, and the one whose message is least
            # helpful: the request was fine, the id is not served.
            _say(f"  {'':<10} -> the provider does not serve this model id for this account")
        return False

    elapsed = (time.perf_counter() - started) * 1000
    _say(f"  {'':<10} ok, {elapsed:.0f} ms")
    return True


def main() -> int:
    configure_logging()
    settings = get_settings()
    session_id = new_session_id()

    # Every model this application can reach for, and what stops working when
    # it does not resolve. A model with no consequence listed is not checked,
    # because a check that nothing depends on is noise.
    targets: list[tuple[str, str, str]] = [
        ("chat", settings.chat_model, "every answer"),
        ("grader", settings.grader_model, "retrieval grading and memory extraction"),
    ]
    if settings.fallback_model.strip():
        targets.append(("fallback", settings.fallback_model, "answers when the chat model fails"))

    _say("\nChecking configured models. One token each.\n")
    broken: list[tuple[str, str]] = []
    for label, model, consequence in targets:
        if not _check(label, model, session_id):
            broken.append((label, consequence))
        _say()

    if not broken:
        _say("All configured models answered.\n")
        return 0

    _say("Not working:\n")
    for label, consequence in broken:
        _say(f"  {label:<10} - this silently disables: {consequence}")
    _say(
        "\nFix the id in .env and run this again. Model ids are listed at "
        "https://openrouter.ai/models - the id is the string under the model "
        "name, such as 'openai/gpt-4o-mini'.\n"
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
