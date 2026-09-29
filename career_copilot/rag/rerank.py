"""Cross-encoder reranking.

Retrieval is a two-stage problem. Dense and BM25 are bi-encoders: query and
document are embedded separately and compared, which is fast enough to run over
a whole corpus but blunt. A cross-encoder scores the query and document
*together* in one pass, which is far more accurate and far too slow for a full
corpus - so it goes second, over a bounded candidate list.

Reranking is an enhancement: if the model fails to load, we return the fused
order rather than failing the query.

**On cost.** Measured on a 2-core CPU, `bge-reranker-base` at the default
512-token window took ~1.3 s per candidate - 17 s for a single question, three
quarters of the whole turn. Three bounds keep that in hand:

- ``MAX_CANDIDATES`` - a cap on how many make it to the cross-encoder at all.
  RRF has already ordered them; the 40th-ranked fusion result is not going to
  win after reranking, so paying to score it is waste.
- ``MAX_SEQUENCE_TOKENS`` - transformer cost scales with sequence length, and
  our chunks rarely need the full 512-token window.
- ``SCORING_CHARS`` - the text handed to the *scorer* is truncated. The full
  passage still goes into the answer context; only the relevance judgement sees
  the shortened version, and relevance is decided in the opening sentences.
"""

from __future__ import annotations

import time
from functools import lru_cache
from typing import Any

from career_copilot.core.config import get_settings
from career_copilot.core.logging import get_logger
from career_copilot.rag.retrieve import Retrieved

__all__ = ["MAX_CANDIDATES", "MAX_SEQUENCE_TOKENS", "SCORING_CHARS", "get_reranker", "rerank"]

log = get_logger(__name__)

# How many fused candidates reach the cross-encoder. Beyond this, RRF's ordering
# stands - the cost of scoring them is not repaid by the ranking change.
MAX_CANDIDATES = 30

# Padding target for the model. Our chunks cap at ~1200 characters (~300 tokens),
# so the default 512 mostly pays for padding.
MAX_SEQUENCE_TOKENS = 320

# Characters of passage text given to the scorer. The answer still receives the
# full passage; this only bounds the relevance judgement.
SCORING_CHARS = 1000


@lru_cache(maxsize=1)
def get_reranker() -> Any | None:
    """Load the cross-encoder once per process. None if unavailable."""
    settings = get_settings()
    if not settings.rerank_enabled:
        return None
    try:
        from sentence_transformers import CrossEncoder
    except ImportError:
        log.warning("sentence-transformers missing - reranking disabled")
        return None

    log.info(
        "loading reranker",
        extra={
            "model": settings.rerank_model,
            "max_length": MAX_SEQUENCE_TOKENS,
            "local_files_only": settings.hf_offline,
        },
    )
    try:
        # See `embeddings.LocalEmbedder` - this is the second model whose load
        # can stall on Hub metadata, and it stalls for exactly the same reason.
        return CrossEncoder(
            settings.rerank_model,
            max_length=MAX_SEQUENCE_TOKENS,
            local_files_only=settings.hf_offline,
        )
    except Exception:
        # The promise at the top of this module is that a reranker which will
        # not load costs quality and nothing else. Only `ImportError` was
        # caught before, which kept that promise for a missing dependency and
        # broke it for everything else - a model absent from the local cache
        # under `CC_HF_OFFLINE`, a corrupt download, a machine out of memory.
        #
        # `None` is returned rather than re-raised so that `lru_cache` stores
        # it: a load that fails is attempted once per process, not once per
        # question.
        log.exception("reranker failed to load - answers will use the fused order")
        return None


def rerank(
    query: str,
    candidates: list[Retrieved],
    *,
    top_k: int | None = None,
) -> list[Retrieved]:
    """Rescore candidates against the query and keep the best.

    The returned score is the cross-encoder logit, which is on a different scale
    from the RRF score it replaces - higher is better, but the absolute value is
    not comparable across queries.
    """
    settings = get_settings()
    limit = top_k or settings.rerank_top_k

    if not candidates:
        return []

    model = get_reranker()
    if model is None:
        return candidates[:limit]

    # Candidates arrive in fused order, so this keeps the most promising ones.
    scored_pool = candidates[:MAX_CANDIDATES]
    overflow = candidates[MAX_CANDIDATES:]
    if overflow:
        log.info(
            "rerank candidate cap applied",
            extra={"scored": len(scored_pool), "skipped": len(overflow)},
        )

    started = time.perf_counter()
    try:
        pairs = [(query, c.text[:SCORING_CHARS]) for c in scored_pool]
        scores = model.predict(pairs, show_progress_bar=False)
    except Exception:
        # Swallowed deliberately - a reranker failure degrades quality but must
        # not lose the results. Logged with traceback so it is never silent.
        log.exception("reranking failed - keeping fused order")
        return candidates[:limit]

    rescored = [
        candidate.model_copy(
            update={
                "score": float(score),
                "found_by": [*candidate.found_by, "rerank"],
            }
        )
        for candidate, score in zip(scored_pool, scores, strict=False)
    ]
    rescored.sort(key=lambda c: -c.score)

    elapsed_ms = (time.perf_counter() - started) * 1000
    log.info(
        "reranked",
        extra={
            "candidates": len(scored_pool),
            "kept": min(limit, len(rescored)),
            "latency_ms": round(elapsed_ms),
            "ms_per_candidate": round(elapsed_ms / len(scored_pool)),
        },
    )
    return rescored[:limit]
