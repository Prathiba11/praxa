import pytest

from career_copilot.core.errors import RetrievalError
from career_copilot.core.types import DocType, Profile
from career_copilot.rag.chunkers import Chunk
from career_copilot.rag.store import VectorStore


class FakeEmbedder:
    """Deterministic 8-dimensional vectors - no model download, instant."""

    model_name = "fake/test-model"
    dimension = 8

    def _vector(self, text: str) -> list[float]:
        words = text.lower().split()
        vec = [0.0] * self.dimension
        for word in words:
            vec[hash(word) % self.dimension] += 1.0
        norm = sum(v * v for v in vec) ** 0.5 or 1.0
        return [v / norm for v in vec]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-fake")
    monkeypatch.setenv("CC_MODEL", "openai/gpt-4o-mini")
    monkeypatch.setenv("CC_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CC_CHROMA_DIR", str(tmp_path / "chroma"))

    from career_copilot.core.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setattr("career_copilot.rag.store.get_embedder", lambda: FakeEmbedder())
    yield VectorStore(persist_dir=str(tmp_path / "chroma"))
    get_settings.cache_clear()


def _chunk(text: str, *, profile: Profile, doc_type=DocType.RESUME, index=0) -> Chunk:
    return Chunk(
        text=text,
        doc_type=doc_type,
        profile=profile,
        source=f"{profile}.md",
        section="Experience",
        chunk_index=index,
    )


def test_empty_store_reports_zero(store):
    assert store.count() == 0


def test_searching_an_empty_store_raises(store):
    with pytest.raises(RetrievalError, match="empty"):
        store.search("anything")


def test_add_then_count(store):
    store.add([_chunk("kubernetes orchestration", profile=Profile.DEVOPS)])
    assert store.count() == 1


def test_add_is_idempotent(store):
    """Deterministic IDs mean re-ingesting updates rather than duplicating."""
    chunk = _chunk("kubernetes orchestration", profile=Profile.DEVOPS)
    store.add([chunk])
    store.add([chunk])
    assert store.count() == 1


def test_search_returns_hits_with_citations(store):
    store.add([_chunk("threat analysis and risk assessment", profile=Profile.AUTOMOTIVE_CYBER)])
    hits = store.search("threat analysis")

    assert hits
    assert "automotive_cyber.md" in hits[0].citation
    assert "Experience" in hits[0].citation
    assert 0.0 <= hits[0].score <= 1.0


def test_where_filter_restricts_results(store):
    store.add(
        [
            _chunk("pipeline automation", profile=Profile.DEVOPS, index=0),
            _chunk("pipeline automation", profile=Profile.AI_ENG, index=1),
        ]
    )
    hits = store.search("pipeline automation", k=5, where={"profile": "devops"})

    assert hits
    assert all(h.metadata["profile"] == "devops" for h in hits)


def test_k_limits_the_number_of_results(store):
    store.add([_chunk(f"chunk number {i}", profile=Profile.DEVOPS, index=i) for i in range(10)])
    assert len(store.search("chunk", k=3)) == 3


def test_reset_empties_the_collection(store):
    store.add([_chunk("something", profile=Profile.DEVOPS)])
    store.reset()
    assert store.count() == 0


def test_embedding_model_mismatch_is_refused(store, monkeypatch, tmp_path):
    """Vectors from two models are not comparable - opening must fail loudly."""
    store.add([_chunk("indexed with the fake model", profile=Profile.DEVOPS)])

    class OtherEmbedder(FakeEmbedder):
        model_name = "different/model"

    monkeypatch.setattr("career_copilot.rag.store.get_embedder", lambda: OtherEmbedder())
    with pytest.raises(RetrievalError, match="re-index"):
        VectorStore(persist_dir=str(tmp_path / "chroma"))
