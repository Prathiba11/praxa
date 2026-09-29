"""Warming the retrieval models at startup.

The thing being protected here is not speed, it is blast radius. This code
runs in a thread during application startup, where there is no request to fail
and nobody to show an error to - so the only acceptable behaviours are "loaded"
and "logged and carried on". A warm-up that can raise is a server that can
refuse to start because a cross-encoder was unavailable.

The second property is that it can be switched off, because the test suite and
every one-shot script must never begin a 1 GB download they will not use.
"""

from __future__ import annotations

import sys

import pytest

from career_copilot.core.config import get_settings
from career_copilot.rag import embeddings as embeddings_module
from career_copilot.rag import rerank as rerank_module
from career_copilot.rag.warmup import warm_in_background, warm_models


class _Embedder:
    model_name = "intfloat/multilingual-e5-base"


@pytest.fixture(autouse=True)
def _settings(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-test-not-a-real-key")
    monkeypatch.setenv("CC_MODEL", "openai/gpt-4o-mini")
    monkeypatch.setenv("CC_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CC_WARM_MODELS", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture()
def loaders(monkeypatch):
    """Stand-ins for the two model loaders, recording that they were called.

    They are patched where they are defined rather than where they are used,
    because `warm_models` imports them inside the function - deliberately, so
    that importing this module does not pull in torch.
    """
    called: list[str] = []

    monkeypatch.setattr(
        "career_copilot.rag.embeddings.get_embedder",
        lambda: called.append("embedder") or _Embedder(),
    )
    monkeypatch.setattr(
        "career_copilot.rag.rerank.get_reranker", lambda: called.append("reranker") or object()
    )
    return called


def test_both_models_are_loaded(loaders):
    warm_models()

    assert loaders == ["embedder", "reranker"]


def test_a_failing_embedder_does_not_stop_the_reranker(monkeypatch, loaders):
    """Both are timed separately, so both are attempted separately.

    They fail for different reasons and one working without the other is a
    perfectly good state to serve from.
    """

    def _explode():
        raise RuntimeError("no such model")

    monkeypatch.setattr("career_copilot.rag.embeddings.get_embedder", _explode)

    warm_models()

    assert loaders == ["reranker"]


def test_a_failing_warmup_never_raises(monkeypatch):
    """There is no request to fail here. Startup must continue regardless."""

    def _explode():
        raise RuntimeError("torch is unhappy")

    monkeypatch.setattr("career_copilot.rag.embeddings.get_embedder", _explode)
    monkeypatch.setattr("career_copilot.rag.rerank.get_reranker", _explode)

    warm_models()  # the assertion is that this line returns


def test_warming_is_off_when_the_setting_says_so(monkeypatch):
    monkeypatch.setenv("CC_WARM_MODELS", "false")
    get_settings.cache_clear()

    def _never():
        raise AssertionError("a model was loaded with warming disabled")

    monkeypatch.setattr("career_copilot.rag.embeddings.get_embedder", _never)

    assert warm_in_background() is None


def test_warming_does_not_block_the_caller(loaders):
    """Startup returns immediately; the thread finishes on its own time."""
    thread = warm_in_background()

    assert thread is not None
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert loaders == ["embedder", "reranker"]


@pytest.mark.parametrize("offline", [True, False])
def test_the_models_are_loaded_from_the_cache_when_told_to(monkeypatch, tmp_path, offline):
    """`CC_HF_OFFLINE` is the difference between seconds and minutes here.

    It reaches the models as `local_files_only`, an argument on each
    constructor - not as `HF_HUB_OFFLINE`, which `huggingface_hub` reads when
    it is imported and which application code therefore cannot set reliably.
    """
    monkeypatch.setenv("CC_HF_OFFLINE", "true" if offline else "false")
    monkeypatch.setenv("CC_EMBED_MODEL", "some/model")
    monkeypatch.setenv("CC_RERANK_MODEL", "some/reranker")
    get_settings.cache_clear()

    seen: dict[str, object] = {}

    class _SentenceTransformer:
        def __init__(self, name, *, local_files_only=False):
            seen["embedder"] = local_files_only

        def get_sentence_embedding_dimension(self):
            return 768

    def _cross_encoder(name, *, max_length=None, local_files_only=False):
        seen["reranker"] = local_files_only
        return object()

    # Swapped at the module level, because both loaders import
    # `sentence_transformers` inside the function that needs it.
    monkeypatch.setitem(
        sys.modules,
        "sentence_transformers",
        type(
            "_Module",
            (),
            {"SentenceTransformer": _SentenceTransformer, "CrossEncoder": _cross_encoder},
        ),
    )
    embeddings_module.get_embedder.cache_clear()
    rerank_module.get_reranker.cache_clear()

    warm_models()

    assert seen == {"embedder": offline, "reranker": offline}

    embeddings_module.get_embedder.cache_clear()
    rerank_module.get_reranker.cache_clear()
