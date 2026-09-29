"""Prove whether traces are actually reaching LangSmith.

    python scripts/check_tracing.py            # diagnose only, spends nothing
    python scripts/check_tracing.py --send     # also send one real trace

The problem this solves: tracing is opt-in and fails silently by design. A
missing key, a disabled flag or the wrong region all look identical from the
outside - an empty project, an hour later, with nothing in the logs to say why.
This walks the chain in order and stops at the first link that is broken,
naming it.

The chain:

1. the flag is on
2. a key is present
3. the `langsmith` package is installed
4. the key is valid **for the region the endpoint points at**
5. a trace sent from this machine can be read back

Steps 1-4 cost nothing. Step 5 needs `--send`: it makes one real model call,
which costs a fraction of a cent, because the only way to prove a trace arrives
is to send one and then ask the server for it.

Reading it back is the point. "We called the SDK without an exception" is not
evidence - the SDK batches in a background thread and swallows an ingest
rejection there, which is exactly how a wrong-region setup looks healthy.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
import uuid
from typing import Any

from career_copilot.core.config import get_settings
from career_copilot.core.errors import CopilotError
from career_copilot.core.logging import configure_logging
from career_copilot.core.tracing import add_run_metadata, traced, tracing_active

# LangSmith writes in the background and its default flush window is seconds,
# not milliseconds. A read that comes back empty on the first try means "not
# yet", so the read is retried before it is believed.
_READ_ATTEMPTS = 10
_READ_WAIT_SECONDS = 3.0

_US_API = "https://api.smith.langchain.com"
_EU_API = "https://eu.api.smith.langchain.com"


def _ok(message: str) -> None:
    print(f"  [ok]   {message}")


def _bad(message: str) -> None:
    print(f"  [FAIL] {message}")


def _note(message: str) -> None:
    print(f"         {message}")


def _mask(secret: str) -> str:
    """Enough of a key to recognise it, not enough to use it."""
    if len(secret) <= 10:
        return "*" * len(secret)
    return f"{secret[:6]}...{secret[-4:]} ({len(secret)} chars)"


# ------------------------------------------------------------------ the chain


def _check_settings() -> tuple[bool, Any]:
    print("\n1. Configuration")
    try:
        settings = get_settings()
    except CopilotError as exc:
        _bad(f"settings could not be loaded: {exc.detail}")
        _note("Fix .env first - nothing else can be checked until it loads.")
        return False, None

    if not settings.tracing_enabled:
        _bad("CC_TRACING_ENABLED is not true - tracing is off by design")
        _note("Add to .env:  CC_TRACING_ENABLED=true")
        return False, settings
    _ok("CC_TRACING_ENABLED=true")

    key = settings.langsmith_api_key.get_secret_value()
    if not key:
        _bad("LANGSMITH_API_KEY is empty - tracing stays off")
        _note("Create a key in LangSmith under Settings -> API keys, then add:")
        _note("  LANGSMITH_API_KEY=lsv2_pt_...")
        return False, settings
    _ok(f"LANGSMITH_API_KEY is set: {_mask(key)}")

    _ok(f"LANGSMITH_PROJECT={settings.langsmith_project}")

    endpoint = settings.langsmith_endpoint
    if endpoint:
        _ok(f"LANGSMITH_ENDPOINT={endpoint}")
        host = endpoint.removeprefix("https://").removeprefix("http://").split("/")[0]
        if host.endswith("smith.langchain.com") and not host.startswith(("api.", "eu.api.")):
            _bad("that is the sign-in address, not the API host")
            _note(f"An EU workspace needs: LANGSMITH_ENDPOINT={_EU_API}")
            return False, settings
    else:
        _ok(f"LANGSMITH_ENDPOINT is unset - the SDK default is used ({_US_API})")
        _note("Correct for a US workspace. If you sign in at eu.smith.langchain.com,")
        _note(f"this is wrong and every trace is rejected: set {_EU_API}")

    return True, settings


def _check_package() -> bool:
    print("\n2. The langsmith package")
    try:
        import langsmith
    except ImportError:
        _bad("langsmith is not installed")
        _note("pip install -r requirements.txt")
        return False
    _ok(f"langsmith {langsmith.__version__}")
    return True


def _check_active() -> bool:
    print("\n3. What the application decided")
    if not tracing_active():
        _bad("tracing_active() is False - the app will not send anything")
        return False
    _ok("tracing_active() is True")
    return True


def _check_credentials(settings: Any) -> bool:
    """Ask the server who we are. Catches a wrong key and a wrong region.

    A key from a US workspace sent to the EU host is not an error the SDK
    reports at trace time - it is a rejection inside a background thread. Here
    it is a failed call with a message.
    """
    print("\n4. The key, against the region it points at")
    from langsmith import Client
    from langsmith.utils import LangSmithError

    endpoint = settings.langsmith_endpoint or _US_API
    client = Client()
    try:
        projects = list(client.list_projects(limit=1))
    except (LangSmithError, OSError) as exc:
        _bad(f"could not authenticate against {endpoint}")
        _note(f"{type(exc).__name__}: {exc}")
        _note("Usual cause: the key belongs to a different region than the endpoint.")
        _note(f"EU workspace -> key from eu.smith.langchain.com and {_EU_API}")
        return False

    _ok(f"authenticated against {endpoint}")
    if projects:
        _note(f"an existing project is visible: {projects[0].name}")
    return True


def _read_run(client: Any, run_id: str) -> Any:
    """Fetch one run, across two generations of the SDK.

    `read_run` is deprecated in favour of `client.runs.retrieve`, which the
    older versions in this project's supported range do not have. Preferring
    the new name and falling back to the old one keeps both working without
    pinning the SDK forward for everybody.

    Returns None when the run is not there, which for the first few attempts
    means "not yet" rather than "never".
    """
    from langsmith.utils import LangSmithError, LangSmithNotFoundError

    runs = getattr(client, "runs", None)
    retrieve = getattr(runs, "retrieve", None)
    reader = retrieve if callable(retrieve) else client.read_run
    try:
        return reader(run_id)
    except (LangSmithNotFoundError, LangSmithError, OSError):
        return None


def _current_run_id() -> str | None:
    from langsmith.run_helpers import get_current_run_tree

    run = get_current_run_tree()
    return str(run.id) if run is not None else None


def _send_and_read_back(settings: Any) -> bool:
    print("\n5. One real trace, sent and read back")
    from langsmith import Client

    marker = uuid.uuid4().hex[:8]
    captured: dict[str, str | None] = {}

    @traced("tracing self-check")
    def run() -> str:
        captured["run_id"] = _current_run_id()
        add_run_metadata(check=True, marker=marker)
        from career_copilot.core.llm import chat

        result = chat(
            [{"role": "user", "content": "Reply with the single word: ok"}],
            session_id=f"tracing-check-{marker}",
            operation="tracing_check",
        )
        return (result.content or "").strip()

    try:
        answer = run()
    except CopilotError as exc:
        _bad(f"the model call failed, so there is no trace to look for: {exc.user_message}")
        _note(f"detail: {exc.detail}")
        return False

    _ok(f"the model answered: {answer!r}")

    run_id = captured.get("run_id")
    if not run_id:
        _bad("no run was opened - @traced did not take effect")
        _note("That means tracing_active() was False when the decorator first ran.")
        return False
    _ok(f"run id {run_id}")

    client = Client()
    # Added in a later SDK than this project's floor. Without it the traces
    # still go out - on the background thread's own schedule - which is what
    # the retry loop below is for either way.
    flush = getattr(client, "flush", None)
    if callable(flush):
        flush()

    for attempt in range(1, _READ_ATTEMPTS + 1):
        stored = _read_run(client, run_id)
        if stored is not None:
            _ok("the trace is on the server - tracing works")
            project = settings.langsmith_project
            host = (settings.langsmith_endpoint or _US_API).replace("api.", "", 1)
            _note(f"See it under project {project!r} at {host}")
            return True
        print(f"         not there yet, waiting ({attempt}/{_READ_ATTEMPTS})...")
        time.sleep(_READ_WAIT_SECONDS)

    _bad("the trace never appeared")
    _note("Sending succeeded but ingest did not accept it. That is almost always")
    _note("the region: an EU workspace with no LANGSMITH_ENDPOINT, or the reverse.")
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check that LangSmith tracing works.")
    parser.add_argument(
        "--send",
        action="store_true",
        help="Send one real trace and read it back. Makes one model call.",
    )
    args = parser.parse_args(argv)

    configure_logging(level="WARNING", as_json=False)
    # The SDK logs its own connection failures, in full, before returning them.
    # This script reports the same failure in a sentence, so the duplicate is
    # noise that buries the answer.
    logging.getLogger("langsmith").setLevel(logging.ERROR)

    print("Checking LangSmith tracing")
    print("=" * 60)

    ok, settings = _check_settings()
    if not ok:
        print("\nTracing is OFF. Nothing has been sent, and nothing was spent.")
        return 1

    if not _check_package() or not _check_active():
        print("\nTracing is OFF. Nothing has been sent, and nothing was spent.")
        return 1

    if not _check_credentials(settings):
        print("\nThe application would send traces, but the server rejects the key.")
        return 1

    if not args.send:
        print("\n" + "=" * 60)
        print("Configuration is correct and the key works.")
        print("Whether a trace actually lands is still unproven - run with --send")
        print("to make one small model call and read the trace back.")
        return 0

    if not _send_and_read_back(settings):
        return 1

    print("\n" + "=" * 60)
    print("Tracing is working end to end.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
