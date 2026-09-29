"""Why is a model call slow only after the cross-encoder has run?

    python scripts/diagnose_latency.py

The observation this exists to explain: on one machine, every OpenRouter call
that follows a reranking pass takes about 45 seconds, and every call that
follows another call takes one or two. `curl` to the same host is fast at all
times, so the network path is not the problem - which leaves two candidates
that a log cannot tell apart:

    idle       the HTTP connection is dropped while reranking runs, and
               re-establishing it from Python is what costs the time
    busy       reranking leaves the process in a state - saturated BLAS
               threads, a starved GIL - that stalls the next network call

They predict different things, so one experiment separates them. Four phases,
one small call each:

    1. warm      three calls back to back                 - the baseline
    2. idle      sleep, doing nothing, then call          - tests "idle"
    3. busy      the same wall-clock time spent on CPU    - tests "busy"
    4. rerank    the real cross-encoder, then call        - the actual case

If phase 2 is slow, the connection is the problem and the fix is keep-alive or
pre-connection. If phase 2 is fast and phase 3 is slow, it is the CPU, and the
fix is thread limits around the model. If only phase 4 is slow, it is something
specific to sentence-transformers rather than CPU load in general.

Cost: six one-token calls, well under a cent.
"""

from __future__ import annotations

import argparse
import sys
import time

from career_copilot.core.config import get_settings
from career_copilot.core.errors import CopilotError
from career_copilot.core.llm import chat
from career_copilot.core.logging import configure_logging
from career_copilot.core.usage import new_session_id

_PROMPT = [{"role": "user", "content": "ping"}]


def _say(text: str = "") -> None:
    print(text, flush=True)


def _call(session_id: str, label: str) -> float:
    """One tiny call, timed from here rather than from inside the client."""
    started = time.perf_counter()
    try:
        chat(_PROMPT, session_id=session_id, operation="diagnose_latency", max_tokens=1)
    except CopilotError as exc:
        _say(f"  {label:<28} FAILED - {exc.detail}")
        return -1.0
    elapsed = time.perf_counter() - started
    flag = "  <-- SLOW" if elapsed > 10 else ""
    _say(f"  {label:<28} {elapsed:6.1f} s{flag}")
    return elapsed


def _burn(seconds: float) -> None:
    """Occupy the CPU the way the cross-encoder does, without loading it.

    Matrix multiplication goes through the same BLAS threads a transformer
    forward pass uses, which is the part of "busy" that might matter.
    """
    try:
        import numpy as np
    except ImportError:
        _say("  numpy not installed - skipping the busy phase")
        return

    size = 900
    left = np.random.rand(size, size)
    right = np.random.rand(size, size)
    deadline = time.perf_counter() + seconds
    while time.perf_counter() < deadline:
        left @ right


def _rerank(seconds: float) -> None:
    """The real thing: load the cross-encoder and score until the time is up."""
    from career_copilot.rag.rerank import get_reranker

    model = get_reranker()
    if model is None:
        _say("  reranker unavailable - skipping the rerank phase")
        return

    pairs = [("what is a TARA?", "A threat analysis and risk assessment." * 8)] * 20
    deadline = time.perf_counter() + seconds
    while time.perf_counter() < deadline:
        model.predict(pairs, show_progress_bar=False)


def main() -> int:
    parser = argparse.ArgumentParser(description="Locate the 45-second stall.")
    parser.add_argument("--gap", type=float, default=25.0, help="seconds per gap (default 25)")
    args = parser.parse_args()

    configure_logging()
    get_settings()
    session_id = new_session_id()

    _say(f"\nSix small calls, {args.gap:.0f}-second gaps. Watch which ones are slow.\n")

    _say("1. warm - three calls, no gap between them")
    _call(session_id, "first call of the process")
    _call(session_id, "immediately after")
    baseline = _call(session_id, "immediately after")

    _say(f"\n2. idle - {args.gap:.0f}s doing nothing, then a call")
    time.sleep(args.gap)
    idle = _call(session_id, f"after {args.gap:.0f}s idle")

    _say(f"\n3. busy - {args.gap:.0f}s of CPU, then a call")
    _burn(args.gap)
    busy = _call(session_id, f"after {args.gap:.0f}s of CPU")

    _say(f"\n4. rerank - {args.gap:.0f}s of the real cross-encoder, then a call")
    _rerank(args.gap)
    rerank = _call(session_id, f"after {args.gap:.0f}s of reranking")

    _say("\n" + "-" * 60)
    _say(f"baseline (no gap):      {baseline:6.1f} s")
    _say(f"after idle:             {idle:6.1f} s")
    _say(f"after CPU:              {busy:6.1f} s")
    _say(f"after reranking:        {rerank:6.1f} s")
    _say("")

    slow = 10.0
    if idle > slow:
        _say("The connection going idle is what costs the time.")
        _say("Fix: keep it alive, or re-establish it before it is needed.")
    elif busy > slow or rerank > slow:
        _say("CPU work before the call is what costs the time, not the gap itself.")
        if rerank > slow and busy <= slow:
            _say("And only the cross-encoder does it - so it is sentence-transformers,")
            _say("not CPU load in general. Thread limits around the model are the lead.")
        else:
            _say("Fix: bound the thread pools the model uses.")
    else:
        _say("Nothing reproduced. The stall needs a longer gap, or it is")
        _say("intermittent - run again with a larger --gap before concluding.")
    _say("")
    return 0


if __name__ == "__main__":
    sys.exit(main())
