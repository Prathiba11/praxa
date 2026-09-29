"""Loading, chunking and indexing, with a real Chroma collection.

The unit tests stub every boundary, which means they cannot see the bugs that
only appear when the pieces meet: metadata that survives chunking but not
indexing, ids that are not as deterministic as intended, filters whose syntax is
right in Python and wrong in Chroma. That is what these cover.

Only the embedder is fake. Everything else on this path is the real code.
"""

from __future__ import annotations

import pytest

from career_copilot.core.errors import RetrievalError
from career_copilot.rag.chunkers import chunk_documents
from career_copilot.rag.loaders import load_all
from career_copilot.rag.store import VectorStore

pytestmark = pytest.mark.slow


def test_loading_infers_type_and_profile_from_the_path(sample_kb):
    kb_dir, resume_dir = sample_kb
    docs = load_all(kb_dir=kb_dir, resume_dir=resume_dir)

    by_source = {doc.source: doc for doc in docs}
    assert len(docs) == 4

    resume = by_source["devops.md"]
    assert str(resume.doc_type) == "resume"
    assert str(resume.profile) == "devops"

    guide = by_source["ats_basics.md"]
    assert str(guide.doc_type) == "guide"
    assert guide.profile is None

    domain = by_source["kubernetes.md"]
    assert str(domain.doc_type) == "domain"
    assert str(domain.profile) == "devops"


def test_resume_sections_are_never_merged(sample_kb):
    """Resumes are chunked section-aware: each `##` heading becomes its own
    chunk however short, because "Languages" and "Certifications" are exactly
    the sections a size threshold would swallow."""
    kb_dir, resume_dir = sample_kb
    chunks = chunk_documents(load_all(kb_dir=kb_dir, resume_dir=resume_dir))

    sections = {c.section for c in chunks if c.source == "devops.md"}
    assert {"Summary", "Experience"} <= sections


def test_short_prose_sections_are_merged_into_one_chunk(sample_kb):
    """The other half of the same decision: reference prose is chunked by size,
    so two short adjacent sections share a chunk rather than becoming two
    fragments too small to retrieve well. The text is kept either way."""
    kb_dir, resume_dir = sample_kb
    chunks = [
        c
        for c in chunk_documents(load_all(kb_dir=kb_dir, resume_dir=resume_dir))
        if c.source == "kubernetes.md"
    ]

    assert len(chunks) == 1
    assert "OOMKilled" in chunks[0].text
    assert chunks[0].section == "Scheduling"


def test_chunk_indices_have_no_gaps(sample_kb):
    kb_dir, resume_dir = sample_kb
    chunks = chunk_documents(load_all(kb_dir=kb_dir, resume_dir=resume_dir))

    for source in {c.source for c in chunks}:
        indices = sorted(c.chunk_index for c in chunks if c.source == source)
        assert indices == list(range(len(indices))), f"gap in {source}"


def test_indexing_then_searching_returns_the_right_document(indexed_kb):
    hits = indexed_kb.search("OOMKilled memory limit container", k=3)
    assert hits
    assert hits[0].metadata["source"] == "kubernetes.md"


def test_metadata_filter_restricts_results(indexed_kb):
    hits = indexed_kb.search("Kubernetes", k=5, where={"doc_type": "resume"})
    assert hits
    assert {hit.metadata["source"] for hit in hits} == {"devops.md"}


def test_citation_includes_the_section(indexed_kb):
    hits = indexed_kb.search("attack feasibility threat scenarios", k=3)
    assert hits
    assert " - " in hits[0].citation


def test_reindexing_is_idempotent(indexed_kb, sample_kb):
    """Deterministic ids mean a second ingest upserts rather than duplicates."""
    before = indexed_kb.count()
    kb_dir, resume_dir = sample_kb
    indexed_kb.add(chunk_documents(load_all(kb_dir=kb_dir, resume_dir=resume_dir)))
    assert indexed_kb.count() == before


def test_searching_an_empty_index_is_a_typed_error(isolated_settings, fake_embedder):
    store = VectorStore()
    with pytest.raises(RetrievalError) as excinfo:
        store.search("anything")
    assert "empty" in str(excinfo.value.detail)


def test_reset_empties_the_collection(indexed_kb):
    assert indexed_kb.count() > 0
    indexed_kb.reset()
    assert indexed_kb.count() == 0


def test_a_different_embedding_model_is_refused(indexed_kb, monkeypatch):
    """Vectors from two models are not comparable, and mixing them degrades
    retrieval with no error. The collection pins the model name for this."""
    from career_copilot.rag import store as store_module

    class _OtherEmbedder:
        model_name = "test/some-other-model"

        def embed_documents(self, texts):
            return [[0.0] for _ in texts]

        def embed_query(self, text):
            return [0.0]

    monkeypatch.setattr(store_module, "get_embedder", _OtherEmbedder)

    with pytest.raises(RetrievalError) as excinfo:
        VectorStore()
    assert "re-index" in str(excinfo.value.detail)


@pytest.mark.live
def test_the_real_embedder_satisfies_the_store_contract(isolated_settings, sample_kb):
    """Downloads the configured model, so it carries the `live` marker.

    The hashing embedder used everywhere else could drift from the real one's
    interface without anything noticing. This is the test that would notice.
    """
    kb_dir, resume_dir = sample_kb
    chunks = chunk_documents(load_all(kb_dir=kb_dir, resume_dir=resume_dir))

    store = VectorStore()
    store.add(chunks[:3])
    assert store.count() == 3
    assert store.search("Kubernetes", k=1)
