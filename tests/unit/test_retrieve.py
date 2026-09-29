"""Hybrid retrieval: tokenisation, filter matching, and RRF arithmetic."""

from unittest.mock import MagicMock, patch

import pytest

from career_copilot.rag.retrieve import RRF_K, _matches, hybrid_search, tokenize
from career_copilot.rag.store import SearchHit
from career_copilot.rag.translate import QueryPlan

# ---------------------------------------------------------------- tokenizer


def test_tokenizer_lowercases_and_keeps_umlauts():
    """German terms must survive - half the job market writes in German."""
    tokens = tokenize("Bedrohungsanalyse und Risikobewertung")
    assert "bedrohungsanalyse" in tokens
    assert "risikobewertung" in tokens


def test_tokenizer_drops_single_characters():
    assert tokenize("a b Kubernetes") == ["kubernetes"]


def test_tokenizer_splits_on_punctuation():
    assert tokenize("ISO/SAE 21434, TARA.") == ["iso", "sae", "21434", "tara"]


# ---------------------------------------------------------------- filters


@pytest.mark.parametrize(
    ("metadata", "where", "expected"),
    [
        ({"profile": "devops"}, None, True),
        ({"profile": "devops"}, {}, True),
        ({"profile": "devops"}, {"profile": "devops"}, True),
        ({"profile": "devops"}, {"profile": "ai_eng"}, False),
        ({"profile": "devops"}, {"profile": {"$in": ["devops", "ai_eng"]}}, True),
        ({"profile": "automotive_cyber"}, {"profile": {"$in": ["devops"]}}, False),
        (
            {"profile": "devops", "doc_type": "resume"},
            {"$and": [{"profile": "devops"}, {"doc_type": "resume"}]},
            True,
        ),
        (
            {"profile": "devops", "doc_type": "domain"},
            {"$and": [{"profile": "devops"}, {"doc_type": "resume"}]},
            False,
        ),
        ({}, {"profile": "devops"}, False),  # missing field never matches
    ],
)
def test_filter_matching(metadata, where, expected):
    assert _matches(metadata, where) is expected


# ---------------------------------------------------------------- fusion


def _hit(doc_id: str) -> SearchHit:
    return SearchHit(
        doc_id=doc_id,
        text=f"text of {doc_id}",
        metadata={"source": f"{doc_id}.md", "section": "Experience"},
        score=0.9,
    )


def _store_returning(hits: list[SearchHit]) -> MagicMock:
    store = MagicMock()
    store.search.return_value = hits
    return store


def test_rrf_score_matches_the_formula():
    """score = sum over lists of 1 / (k + rank). Hand-computed, not recomputed."""
    plan = QueryPlan(original="only query")
    with patch(
        "career_copilot.rag.retrieve.VectorStore",
        return_value=_store_returning([_hit("a"), _hit("b")]),
    ):
        results = hybrid_search(plan, use_bm25=False)

    assert results[0].doc_id == "a"
    assert results[0].score == pytest.approx(1.0 / (RRF_K + 1))
    assert results[1].score == pytest.approx(1.0 / (RRF_K + 2))


def test_a_chunk_found_by_two_queries_outranks_one_found_by_one():
    """The whole point of fusion: agreement across phrasings wins."""
    plan = QueryPlan(original="q1", paraphrases=["q2"])
    store = MagicMock()
    store.search.side_effect = [
        [_hit("shared"), _hit("only_first")],
        [_hit("shared"), _hit("only_second")],
    ]

    with patch("career_copilot.rag.retrieve.VectorStore", return_value=store):
        results = hybrid_search(plan, use_bm25=False)

    assert results[0].doc_id == "shared"
    assert results[0].score == pytest.approx(2.0 / (RRF_K + 1))


def test_found_by_records_retriever_and_phrasing():
    """This is what the RAG-trace expander shows the user."""
    plan = QueryPlan(original="q1", paraphrases=["q2"])
    store = MagicMock()
    store.search.side_effect = [[_hit("shared")], [_hit("shared")]]

    with patch("career_copilot.rag.retrieve.VectorStore", return_value=store):
        results = hybrid_search(plan, use_bm25=False)

    assert results[0].found_by == ["dense:original", "dense:paraphrase"]


def test_final_k_limits_the_result_count():
    plan = QueryPlan(original="q")
    hits = [_hit(f"doc{i}") for i in range(30)]

    with patch("career_copilot.rag.retrieve.VectorStore", return_value=_store_returning(hits)):
        results = hybrid_search(plan, use_bm25=False, final_k=5)

    assert len(results) == 5


def test_citation_includes_source_and_section():
    plan = QueryPlan(original="q")
    with patch(
        "career_copilot.rag.retrieve.VectorStore", return_value=_store_returning([_hit("a")])
    ):
        results = hybrid_search(plan, use_bm25=False)

    assert results[0].citation == "a.md - Experience"
