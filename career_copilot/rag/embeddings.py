"""Embedding provider adapter.

Local sentence-transformers by default: free, offline, multilingual, and your CV
never leaves the machine - which is the GDPR answer as much as a cost one.

The e5 model family expects prefixes - "query: " on searches, "passage: " on
stored documents. Omitting them costs retrieval quality with no error at all,
so the prefixing lives here rather than in every caller.
"""

from __future__ import annotations

from collections.abc import Sequence
from functools import lru_cache
from typing import Protocol

from career_copilot.core.config import get_settings
from career_copilot.core.errors import ConfigError, RetrievalError
from career_copilot.core.logging import get_logger

__all__ = ["Embedder", "get_embedder"]

log = get_logger(__name__)

_PREFIXED_FAMILIES = ("e5", "bge-m3", "multilingual-e5")


class Embedder(Protocol):
    model_name: str
    dimension: int

    def embed_documents(self, texts: list[str]) -> list[Sequence[float]]: ...
    def embed_query(self, text: str) -> Sequence[float]: ...


class LocalEmbedder:
    """sentence-transformers, loaded once per process."""

    def __init__(self, model_name: str, *, local_files_only: bool = False) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:  # pragma: no cover - dependency guard
            raise ConfigError("sentence-transformers is not installed") from exc

        self.model_name = model_name
        self._needs_prefix = any(f in model_name.lower() for f in _PREFIXED_FAMILIES)

        log.info(
            "loading embedding model",
            extra={"model": model_name, "local_files_only": local_files_only},
        )
        # `local_files_only` is what stops sentence-transformers asking the Hub
        # about this repository before it will use its own cache. Passed as an
        # argument rather than set through `HF_HUB_OFFLINE`, because that
        # variable is read by `huggingface_hub` when it is imported - setting
        # it from application code is a race against our own import order.
        self._model = SentenceTransformer(model_name, local_files_only=local_files_only)

        # The method was renamed in newer sentence-transformers; support both.
        get_dim = getattr(
            self._model, "get_embedding_dimension", self._model.get_sentence_embedding_dimension
        )
        dim = get_dim()
        if dim is None:
            raise ConfigError(f"model {model_name!r} reported no embedding dimension")
        self.dimension = int(dim)

    def _encode(self, texts: list[str], prefix: str) -> list[Sequence[float]]:
        if not texts:
            return []
        prepared = [f"{prefix}{t}" for t in texts] if self._needs_prefix else texts
        try:
            vectors = self._model.encode(
                prepared, normalize_embeddings=True, show_progress_bar=False
            )
        except Exception as exc:  # any model failure surfaces as a retrieval failure
            raise RetrievalError(f"embedding failed: {type(exc).__name__}") from exc
        return [v.tolist() for v in vectors]

    def embed_documents(self, texts: list[str]) -> list[Sequence[float]]:
        return self._encode(texts, "passage: ")

    def embed_query(self, text: str) -> Sequence[float]:
        return self._encode([text], "query: ")[0]


@lru_cache(maxsize=1)
def get_embedder() -> Embedder:
    """One embedder per process - loading the model takes seconds."""
    settings = get_settings()
    if settings.embed_provider == "hf":
        return LocalEmbedder(settings.embed_model, local_files_only=settings.hf_offline)
    raise ConfigError(
        f"embedding provider {settings.embed_provider!r} is not implemented; "
        "OpenRouter does not currently expose an embeddings endpoint"
    )
