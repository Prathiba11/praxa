"""Hybrid search and reranking over a real index.

Fusion is where the two retrievers meet, and it is the part unit tests are worst
at: BM25 over a fake corpus and dense search over a fake store can both pass
while the combination returns nothing, because the ids they produce do not line
up. These tests use one real Chroma collection and the real BM25 index built
from it.
"""

from __future__ import annotations

import pytest

from career_copilot.rag import rerank as rerank_module
from career_copilot.rag.rerank import rerank
from career_copilot.rag.retrieve import hybrid_search
from career_copilot.rag.translate import QueryPlan

pytestmark = pytest.mark.slow


def _plan(question: str, *paraphrases: str) -> QueryPlan:
    return QueryPlan(original=question, keywords=list(paraphrases))


def test_dense_and_bm25_both_contribute(indexed_kb):
    results = hybrid_search(_plan("OOMKilled memory limit"), use_bm25=True, use_dense=True)
    assert results

    labels = {label for item in results for label in item.found_by}
    assert any("dense" in label for label in labels)
    assert any("bm25" in label for label in labels)


def test_dense_only_never_claims_bm25(indexed_kb):
    results = hybrid_search(_plan("OOMKilled memory limit"), use_bm25=False, use_dense=True)
    assert results
    assert not any("bm25" in label for item in results for label in item.found_by)


def test_bm25_only_still_returns_results(indexed_kb):
    results = hybrid_search(_plan("OOMKilled"), use_bm25=True, use_dense=False)
    assert results
    assert results[0].metadata["source"] == "kubernetes.md"


def test_fusion_finds_what_a_single_retriever_would_rank_lower(indexed_kb):
    """An exact rare term is BM25's strength; the hashing embedder is weak at
    it. Fusion should surface it regardless of which half found it."""
    results = hybrid_search(_plan("OOMKilled"), use_bm25=True, use_dense=True)
    sources = [item.metadata["source"] for item in results]
    assert "kubernetes.md" in sources


def test_metadata_filter_flows_through_fusion(indexed_kb):
    results = hybrid_search(_plan("Kubernetes"), where={"doc_type": "resume"})
    assert results
    assert {item.metadata["source"] for item in results} == {"devops.md"}


def test_final_k_bounds_the_candidate_list(indexed_kb):
    results = hybrid_search(_plan("Kubernetes"), final_k=2)
    assert len(results) <= 2


def test_results_carry_the_metadata_the_pipeline_relies_on(indexed_kb):
    results = hybrid_search(_plan("threat analysis and risk assessment"))
    assert results
    item = results[0]
    assert item.metadata.get("source")
    assert item.metadata.get("doc_type")
    assert item.citation
    assert item.text.strip()


def test_disabled_reranking_returns_the_fused_order(indexed_kb):
    """CC_RERANK_ENABLED is false in the isolated settings, so this is the
    configuration CI runs in - no cross-encoder download."""
    candidates = hybrid_search(_plan("Kubernetes"))
    kept = rerank("Kubernetes", candidates, top_k=2)
    assert [c.doc_id for c in kept] == [c.doc_id for c in candidates[:2]]


def test_a_broken_reranker_degrades_instead_of_failing(indexed_kb, monkeypatch):
    """Reranking is an enhancement. If the model misbehaves the query must
    still return results, and the failure must be logged rather than silent."""

    class _Exploding:
        def predict(self, pairs, **kwargs):
            raise RuntimeError("cross-encoder unavailable")

    monkeypatch.setattr(rerank_module, "get_reranker", lambda: _Exploding())

    candidates = hybrid_search(_plan("Kubernetes"))
    kept = rerank("Kubernetes", candidates, top_k=3)
    assert kept
    assert [c.doc_id for c in kept] == [c.doc_id for c in candidates[:3]]


def test_reranking_reorders_and_labels(indexed_kb, monkeypatch):
    """A stub cross-encoder that prefers whatever is last proves the rescoring
    path actually reorders, without downloading 300 MB to find out."""

    class _ReversingEncoder:
        def predict(self, pairs, **kwargs):
            return list(range(len(pairs)))

    monkeypatch.setattr(rerank_module, "get_reranker", lambda: _ReversingEncoder())

    candidates = hybrid_search(_plan("Kubernetes"))
    assert len(candidates) >= 2

    kept = rerank("Kubernetes", candidates, top_k=len(candidates))
    assert kept[0].doc_id == candidates[-1].doc_id
    assert "rerank" in kept[0].found_by
