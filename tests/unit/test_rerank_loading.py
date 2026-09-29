"""Loading the cross-encoder, and what happens when it will not load.

The module's own promise is that reranking is an enhancement: a model that
fails costs answer quality and nothing else. That promise was only kept for a
missing dependency - every other way a load can fail propagated out and took
the query with it, which matters most under `CC_HF_OFFLINE`, where a model
absent from the local cache is exactly such a failure.

The `predict`-fails case lives in `tests/integration/test_retrieval_stack.py`.
This file is about the load itself.
"""

from __future__ import annotations

import sys

import pytest

from career_copilot.core.config import get_settings
from career_copilot.rag import rerank as rerank_module
from career_copilot.rag.rerank import get_reranker


@pytest.fixture(autouse=True)
def _settings(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-test-not-a-real-key")
    monkeypatch.setenv("CC_MODEL", "openai/gpt-4o-mini")
    monkeypatch.setenv("CC_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CC_RERANK_ENABLED", "true")
    monkeypatch.setenv("CC_RERANK_MODEL", "some/reranker")
    get_settings.cache_clear()
    get_reranker.cache_clear()
    yield
    get_settings.cache_clear()
    get_reranker.cache_clear()


def _install(cross_encoder) -> None:
    sys.modules["sentence_transformers"] = type(
        "_Module", (), {"CrossEncoder": staticmethod(cross_encoder)}
    )


@pytest.fixture()
def fake_sentence_transformers(monkeypatch):
    """Swapped at module level: `get_reranker` imports inside the function."""
    original = sys.modules.get("sentence_transformers")
    yield _install
    if original is None:
        sys.modules.pop("sentence_transformers", None)
    else:
        sys.modules["sentence_transformers"] = original


def test_a_model_that_will_not_load_is_not_an_error(fake_sentence_transformers):
    """The commonest cause under offline mode: not in the local cache."""
    attempts: list[int] = []

    def _missing(*_args, **_kwargs):
        attempts.append(1)
        raise OSError("some/reranker is not cached and local_files_only is set")

    fake_sentence_transformers(_missing)

    assert get_reranker() is None
    assert attempts == [1]


def test_a_failed_load_is_attempted_once_per_process(fake_sentence_transformers):
    """`None` is cached, so a broken model costs one attempt, not one per question.

    Re-raising would leave `lru_cache` with nothing stored and every question
    would pay for the same failing load again - which, when the cause is a
    network stall, is the slowest possible way to fail.
    """
    attempts: list[int] = []

    def _missing(*_args, **_kwargs):
        attempts.append(1)
        raise OSError("not cached")

    fake_sentence_transformers(_missing)

    get_reranker()
    get_reranker()
    get_reranker()

    assert attempts == [1]


def test_reranking_switched_off_loads_nothing(monkeypatch, fake_sentence_transformers):
    monkeypatch.setenv("CC_RERANK_ENABLED", "false")
    get_settings.cache_clear()

    def _never(*_args, **_kwargs):
        raise AssertionError("a model was loaded with reranking disabled")

    fake_sentence_transformers(_never)

    assert get_reranker() is None


def test_the_offline_setting_reaches_the_model(monkeypatch, fake_sentence_transformers):
    seen: dict[str, object] = {}

    def _record(name, *, max_length=None, local_files_only=False):
        seen.update(name=name, max_length=max_length, local_files_only=local_files_only)
        return object()

    monkeypatch.setenv("CC_HF_OFFLINE", "true")
    get_settings.cache_clear()
    fake_sentence_transformers(_record)

    assert get_reranker() is not None
    assert seen["name"] == "some/reranker"
    assert seen["local_files_only"] is True
    assert seen["max_length"] == rerank_module.MAX_SEQUENCE_TOKENS
