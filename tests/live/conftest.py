"""Guard for the live suite, and the session every live test runs inside.

Two jobs, and the first one used to do the second one's job badly.

**The guard.** Without it, running `pytest -m live` on a machine with no key -
or with an expired one - produces a screenful of red that all means the same
thing, and none of it means "the defence failed". A reviewer glancing at that
output would reasonably conclude the security tests are broken. One cheap call
decides it: a single token, once per session, rather than one authentication
failure per test.

**The session.** `core.llm.chat` refuses a call it cannot attribute to a
session, because an unattributed call is unbudgeted and unrecorded - the exact
hole that module exists to close. In the application a turn opens
`use_session(...)` before anything else; a test is a turn too, and has to do the
same. `run_agent` opens its own, but `answer_question` does not, so six of the
eight tests here need one from outside.

That was the bug this file shipped with. The guard called `chat` with no
session, `chat` raised `ConfigError`, and the guard reported it as a missing API
key and skipped all eight tests. The suite looked like it had been run and
deliberately passed over, when in fact it had never executed once. It went
unnoticed because `-m 'not live'` is the default, so nothing ran the guard.

The lesson is the same one `scripts/check_models.py` exists for: a check that
fails open has to say *what* it saw, not what it assumes it saw. The skip
messages below quote the real error instead of naming a cause.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from career_copilot.core.errors import ConfigError, CopilotError
from career_copilot.core.llm import chat
from career_copilot.core.session import use_session
from career_copilot.core.usage import new_session_id


@pytest.fixture(scope="session", autouse=True)
def _needs_a_working_key() -> None:
    """Skip the whole live suite unless the model is actually reachable."""
    try:
        with use_session(new_session_id()):
            chat([{"role": "user", "content": "ping"}], operation="live_guard", max_tokens=1)
    except ConfigError as exc:
        # Missing key, placeholder key, or a mistake in this file. The detail
        # says which - do not claim to know before reading it.
        pytest.skip(f"the live suite cannot make a model call - {exc}")
    except CopilotError as exc:
        # Rate limited, upstream down, no network. Not a finding either.
        pytest.skip(f"the model is not reachable right now - {exc}")


@pytest.fixture(autouse=True)
def _one_session_per_test() -> Iterator[str]:
    """Every live test is a turn, so every live test gets a session.

    Function-scoped on purpose: each test is then budgeted and recorded
    separately in `data/usage.jsonl`, which is what makes the cost of this suite
    readable afterwards. Nesting is safe - `run_agent` opening its own session
    inside this one restores this one on the way out.
    """
    with use_session(new_session_id()) as session_id:
        yield session_id
