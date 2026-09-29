"""Loading the retrieval models before anyone asks a question.

Two transformer models sit behind a search: the embedder that turns a question
into a vector, and the cross-encoder that reranks what came back. Both are
`lru_cache`d - loaded once per process - and both are loaded **lazily**, on the
first call that needs them.

Lazily means "inside the first request". The user asks a question and waits
through both model loads before retrieval has even started, and every question
after that is fast. That is the worst possible place to put a fixed cost: it
lands entirely on the first person to use the application, who is also the
person forming an opinion of whether it works.

**Where the time actually goes.** Not the weights - those come off disk in
about a second. It is the network. `sentence-transformers` asks the Hugging
Face Hub about each repository before it will use its own cache, and on a
machine where outbound HTTPS is inspected, each of those requests can take the
better part of a minute. Two models, several requests each. `CC_HF_OFFLINE`
removes them entirely once the models have been downloaded once, which is why
the log line carries it: a slow warm-up reading `hf_offline: false` is that
problem, not a mystery.

**It runs in a thread, and failure is not fatal.** The server must answer HTTP
the moment it starts, not several seconds later, and a machine that cannot load
the reranker should still start and still answer questions - reranking is an
enhancement, and the lazy path will simply try again on the first question.
"""

from __future__ import annotations

import threading
import time

from career_copilot.core.config import get_settings
from career_copilot.core.logging import get_logger

__all__ = ["warm_in_background", "warm_models"]

log = get_logger(__name__)


def warm_models() -> None:
    """Load the embedder and the reranker. Blocking. Never raises.

    Each is loaded separately and timed separately, because when this is slow
    the only useful question is *which one* was slow.
    """
    offline = get_settings().hf_offline
    log.info("warming retrieval models", extra={"hf_offline": offline})

    # Imported here, not at module scope: importing these pulls in torch, and
    # a process that never answers a question should not pay for that either.
    from career_copilot.rag.embeddings import get_embedder
    from career_copilot.rag.rerank import get_reranker

    started = time.perf_counter()
    try:
        embedder = get_embedder()
        log.info(
            "embedder ready",
            extra={
                "model": embedder.model_name,
                "ms": round((time.perf_counter() - started) * 1000),
            },
        )
    except Exception:
        # The first question will try again through the lazy path and fail
        # there with a message the user sees. Nothing is gained by crashing
        # the server at startup instead.
        log.exception("could not warm the embedder - the first question will load it")

    started = time.perf_counter()
    try:
        reranker = get_reranker()
        log.info(
            "reranker ready",
            extra={
                "loaded": reranker is not None,
                "ms": round((time.perf_counter() - started) * 1000),
            },
        )
    except Exception:
        log.exception("could not warm the reranker - answers will use the fused order")

    if not offline:
        log.info(
            "retrieval models were warmed with the Hub reachable - set CC_HF_OFFLINE=true "
            "in .env to load them from the local cache instead, now they are downloaded"
        )


def warm_in_background() -> threading.Thread | None:
    """Start the warm-up without blocking the caller.

    Returns the thread, or None when warming is switched off - which is what
    the tests do, and what anyone running a one-shot command wants.
    """
    if not get_settings().warm_models:
        log.debug("model warm-up disabled")
        return None

    thread = threading.Thread(target=warm_models, name="warm-retrieval-models", daemon=True)
    thread.start()
    return thread
