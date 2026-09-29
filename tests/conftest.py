"""Fixtures shared by the integration and functional suites.

Three problems every test above the unit level has to solve, solved once here.

**Settings are cached and read your real `.env`.** A test that does not isolate
them will write into the Chroma directory and SQLite file you actually use.
``isolated_settings`` redirects both at ``tmp_path`` and clears every cache that
would otherwise hold a stale handle.

**The embedding model is a 1 GB download.** Integration tests need a real vector
store, not a real transformer. ``fake_embedder`` substitutes a deterministic
hashing embedder, so Chroma, chunking, metadata filtering, BM25 and fusion all
stay real while the tests run in milliseconds and CI needs no model cache. The
real embedder is exercised by the ``live``-marked test in `test_indexing.py`.

**The LLM must never be called.** Not "there is no key, so it cannot be" -
that was the old claim, and it was wrong on any machine with a populated
`.env`. `_no_live_model_calls` refuses at the client, so a test that forgets to
script a model fails fast and locally instead of quietly buying an answer.

**Nothing may be sent to LangSmith.** A developer with tracing switched on in
their own `.env` would otherwise have every test run ship traces to their
workspace - spending quota and filling a project with runs that never happened
in an application. `_no_tracing` forces it off for every test, and the handful
that exercise tracing turn it back on themselves.
"""

from __future__ import annotations

import pytest

from career_copilot.core import llm as llm_module
from career_copilot.core import tracing
from career_copilot.core.config import get_settings
from career_copilot.core.errors import ConfigError
from career_copilot.rag import rerank as rerank_module
from career_copilot.rag import store as store_module
from career_copilot.storage import db as db_module
from tests.helpers import HashingEmbedder


def _clear_caches() -> None:
    """Every lru_cache that would otherwise survive a settings change.

    `get_reranker` is looked up defensively: a test may have monkeypatched it
    with a plain function, and fixture teardown runs before monkeypatch undoes
    its patches, so the attribute is not always the lru_cache wrapper.
    """
    get_settings.cache_clear()
    clear_reranker = getattr(rerank_module.get_reranker, "cache_clear", None)
    if clear_reranker is not None:
        clear_reranker()
    db_module.reset_engine()


@pytest.fixture(autouse=True)
def _no_live_model_calls(request, monkeypatch):
    """No test reaches a model provider. Ever, unless it is marked `live`.

    "Nothing here provides a working API key" was not the guarantee it sounded
    like. Several helpers - `analyse_query`, `expand_query`, the retrieval
    grader - are deliberately written to fail open, so on a machine that *does*
    have a key in `.env` they made real requests, swallowed whatever came back,
    and passed. The tests still asserted the right things; they just did it
    slowly, over the network, on someone's money.

    Refusing at the client is what catches every one of them at once, whichever
    module imported `chat`. `ConfigError` is a `CopilotError`, so the fail-open
    paths handle it exactly as they handle a real outage - which is the
    behaviour those tests meant to exercise in the first place.
    """
    if "live" in request.keywords:
        return

    def _refuse() -> object:
        raise ConfigError(
            "a test tried to reach the model provider - script the model, or mark it `live`"
        )

    monkeypatch.setattr(llm_module, "get_client", _refuse)


@pytest.fixture(autouse=True)
def _no_tracing(monkeypatch):
    """Tracing off for every test, whatever is in the developer's `.env`.

    **Set, never delete.** Deleting an environment variable does not make a
    setting unset - pydantic-settings simply falls through to the next source,
    which is `.env`. So `monkeypatch.delenv("CC_TRACING_ENABLED")` on a machine
    whose `.env` switches tracing on leaves it switched on, and the tests that
    assert it is off fail for a reason that has nothing to do with the code.
    An explicit value wins, because the environment outranks `.env`.

    The three `LANGSMITH_*` names are registered even though nothing reads them
    here: `core.tracing._resolve` writes them with a plain assignment, which
    monkeypatch cannot know about. Naming them is what gets them removed again
    afterwards, so a test that turns tracing on cannot leak into the next one.
    """
    monkeypatch.setenv("CC_TRACING_ENABLED", "false")
    monkeypatch.setenv("LANGSMITH_API_KEY", "")
    monkeypatch.setenv("LANGSMITH_ENDPOINT", "")
    monkeypatch.delenv("LANGSMITH_TRACING", raising=False)
    monkeypatch.delenv("LANGSMITH_PROJECT", raising=False)

    get_settings.cache_clear()
    tracing.reset_tracing()
    yield
    get_settings.cache_clear()
    tracing.reset_tracing()


@pytest.fixture(autouse=True)
def _no_model_warmup(monkeypatch):
    """No test starts loading a transformer in a background thread.

    `create_app` warms the embedder and the reranker on startup, which is right
    for a running server and catastrophic for a test suite: the API tests build
    an app per test, and each one would begin a 1 GB download that nothing waits
    for and nothing cancels.

    Set, not deleted - for the reason spelled out in `_no_tracing` above.
    """
    monkeypatch.setenv("CC_WARM_MODELS", "false")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture()
def isolated_settings(tmp_path, monkeypatch):
    """Point Chroma, SQLite and the model config at a throwaway directory.

    Environment variables win over `.env` in pydantic-settings, so this holds
    even on a machine with a fully populated `.env`.
    """
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-test-not-a-real-key")
    monkeypatch.setenv("CC_MODEL", "test/model")
    monkeypatch.setenv("CC_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CC_CHROMA_DIR", str(tmp_path / "chroma"))
    monkeypatch.setenv("CC_DB_PATH", str(tmp_path / "career_copilot.db"))
    monkeypatch.setenv("CC_RERANK_ENABLED", "false")
    monkeypatch.setenv("CC_LOG_LEVEL", "WARNING")

    _clear_caches()
    yield get_settings()
    _clear_caches()


@pytest.fixture()
def fake_embedder(monkeypatch):
    """Replace the transformer with the hashing embedder.

    Patched on `store`, not on `embeddings`, because `store` imported the
    factory by name at module load.
    """
    embedder = HashingEmbedder()
    monkeypatch.setattr(store_module, "get_embedder", lambda: embedder)
    return embedder


@pytest.fixture()
def sample_kb(tmp_path):
    """A four-document knowledge base with a known shape.

    Deliberately small and deliberately overlapping: two documents mention
    Kubernetes, so a filter or a ranking decision has something to get wrong.
    Returns the two roots `load_all` accepts.
    """
    kb_dir = tmp_path / "kb"
    resume_dir = tmp_path / "resumes"
    (kb_dir / "guides").mkdir(parents=True)
    (kb_dir / "domain" / "devops").mkdir(parents=True)
    (kb_dir / "domain" / "automotive_cyber").mkdir(parents=True)
    resume_dir.mkdir(parents=True)

    (kb_dir / "guides" / "ats_basics.md").write_text(
        "# ATS Basics\n\n"
        "## Formatting\n"
        "Applicant tracking systems parse plain single-column layouts. Avoid tables,\n"
        "text boxes and images, which many parsers discard silently.\n\n"
        "## Keywords\n"
        "Mirror the vocabulary of the posting wherever the underlying fact is true.\n",
        encoding="utf-8",
    )
    (kb_dir / "domain" / "devops" / "kubernetes.md").write_text(
        "# Kubernetes\n\n"
        "## Scheduling\n"
        "The scheduler places pods onto nodes according to requests and limits.\n\n"
        "## OOMKilled\n"
        "A container exceeding its memory limit is terminated by the kernel and\n"
        "reported as OOMKilled. Raise the limit or reduce the workload footprint.\n",
        encoding="utf-8",
    )
    (kb_dir / "domain" / "automotive_cyber" / "iso_21434.md").write_text(
        "# ISO/SAE 21434\n\n"
        "## TARA\n"
        "Threat analysis and risk assessment identifies damage scenarios, threat\n"
        "scenarios and attack paths, then rates attack feasibility.\n\n"
        "## Work Products\n"
        "Each clause defines work products that evidence conformity.\n",
        encoding="utf-8",
    )
    (resume_dir / "devops.md").write_text(
        "# DevOps CV\n\n"
        "## Summary\n"
        "Platform engineer working with Kubernetes, Terraform and GitLab CI.\n\n"
        "## Experience\n"
        "- Operated Kubernetes clusters and reduced pipeline build time.\n"
        "- Built Prometheus dashboards for service reliability.\n",
        encoding="utf-8",
    )
    return kb_dir, resume_dir


@pytest.fixture()
def indexed_kb(isolated_settings, fake_embedder, sample_kb):
    """The sample knowledge base, chunked and indexed in a real Chroma store."""
    from career_copilot.rag.chunkers import chunk_documents
    from career_copilot.rag.loaders import load_all
    from career_copilot.rag.store import VectorStore

    kb_dir, resume_dir = sample_kb
    store = VectorStore()
    store.add(chunk_documents(load_all(kb_dir=kb_dir, resume_dir=resume_dir)))
    return store
