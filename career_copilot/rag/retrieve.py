"""Hybrid retrieval: dense + BM25, fused with reciprocal rank fusion.

The two methods fail differently, which is why running both wins:

- Embeddings blur exact strings. Ask for "ISO 21434" and dense search may return
  "ISO 26262" - semantically almost identical, practically a different standard.
  BM25 matches the literal token.
- BM25 has no idea "threat modelling" and "Bedrohungsanalyse" are related.
  Embeddings do.

Their scores are incomparable (BM25 might say 14.7, cosine 0.83), so RRF fuses
on rank position instead of score. Documents both methods like float to the top.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

from pydantic import BaseModel, Field
from rank_bm25 import BM25Okapi

from career_copilot.core.logging import get_logger
from career_copilot.rag.store import VectorStore
from career_copilot.rag.translate import QueryPlan

__all__ = ["BM25Index", "Retrieved", "hybrid_search", "tokenize"]

log = get_logger(__name__)

RRF_K = 60  # the standard damping constant; larger = flatter rank weighting
_TOKEN = re.compile(r"\w+", re.UNICODE)


def tokenize(text: str) -> list[str]:
    """Unicode-aware, so German umlauts survive. Single characters are noise."""
    return [t for t in _TOKEN.findall(text.lower()) if len(t) > 1]


class Retrieved(BaseModel):
    doc_id: str
    text: str
    metadata: dict[str, Any]
    score: float
    found_by: list[str] = Field(default_factory=list)

    @property
    def citation(self) -> str:
        source = self.metadata.get("source", "unknown")
        section = self.metadata.get("section")
        return f"{source} - {section}" if section else str(source)


def _matches(metadata: dict[str, Any], where: dict[str, Any] | None) -> bool:
    """Apply a Chroma-style filter in Python, for the BM25 side."""
    if not where:
        return True
    if "$and" in where:
        return all(_matches(metadata, clause) for clause in where["$and"])

    for field, condition in where.items():
        value = metadata.get(field)
        if isinstance(condition, dict) and "$in" in condition:
            if value not in condition["$in"]:
                return False
        elif value != condition:
            return False
    return True


class BM25Index:
    """Lexical index over the same corpus the vector store holds."""

    def __init__(self, store: VectorStore) -> None:
        self._docs = store.all_documents()
        corpus = [tokenize(text) for _, text, _ in self._docs]
        self._bm25 = BM25Okapi(corpus) if corpus else None
        log.info("bm25 index built", extra={"documents": len(self._docs)})

    def search(
        self, query: str, *, k: int = 10, where: dict[str, Any] | None = None
    ) -> list[tuple[str, str, dict[str, Any]]]:
        if self._bm25 is None:
            return []

        scores = self._bm25.get_scores(tokenize(query))
        ranked = sorted(zip(self._docs, scores, strict=False), key=lambda p: -p[1])

        results: list[tuple[str, str, dict[str, Any]]] = []
        for (doc_id, text, metadata), score in ranked:
            if score <= 0:
                break
            if not _matches(metadata, where):
                continue
            results.append((doc_id, text, metadata))
            if len(results) >= k:
                break
        return results


@lru_cache(maxsize=1)
def _cached_index() -> BM25Index:
    """Built once per process; re-ingesting requires a restart to pick up."""
    return BM25Index(VectorStore())


def hybrid_search(
    plan: QueryPlan,
    *,
    where: dict[str, Any] | None = None,
    k_per_query: int = 10,
    final_k: int = 20,
    use_bm25: bool = True,
    use_dense: bool = True,
) -> list[Retrieved]:
    """Run every query in the plan through both retrievers and fuse by rank.

    use_bm25 / use_dense exist for the A/B comparison: turning one off gives the
    naive baseline to measure hybrid against.
    """
    store = VectorStore()
    fused: dict[str, float] = {}
    seen: dict[str, tuple[str, dict[str, Any]]] = {}
    found_by: dict[str, list[str]] = {}

    def _absorb(doc_id: str, text: str, metadata: dict[str, Any], rank: int, label: str) -> None:
        fused[doc_id] = fused.get(doc_id, 0.0) + 1.0 / (RRF_K + rank)
        seen.setdefault(doc_id, (text, metadata))
        found_by.setdefault(doc_id, []).append(label)

    for strategy, query in plan.labelled():
        if use_dense:
            for rank, hit in enumerate(store.search(query, k=k_per_query, where=where), start=1):
                _absorb(hit.doc_id, hit.text, hit.metadata, rank, f"dense:{strategy}")

        if use_bm25:
            index = _cached_index()
            for rank, (doc_id, text, meta) in enumerate(
                index.search(query, k=k_per_query, where=where), start=1
            ):
                _absorb(doc_id, text, meta, rank, f"bm25:{strategy}")

    # Keyword-only BM25 pass: exact technical terms the phrasings may have lost.
    if use_bm25 and plan.keywords:
        index = _cached_index()
        keyword_query = " ".join(plan.keywords)
        for rank, (doc_id, text, meta) in enumerate(
            index.search(keyword_query, k=k_per_query, where=where), start=1
        ):
            _absorb(doc_id, text, meta, rank, "bm25:keywords")

    results = [
        Retrieved(
            doc_id=doc_id,
            text=seen[doc_id][0],
            metadata=seen[doc_id][1],
            score=score,
            found_by=found_by[doc_id],
        )
        for doc_id, score in sorted(fused.items(), key=lambda p: -p[1])
    ][:final_k]

    log.info(
        "hybrid search complete",
        extra={
            "queries": len(plan.labelled()),
            "candidates": len(fused),
            "returned": len(results),
        },
    )
    return results
