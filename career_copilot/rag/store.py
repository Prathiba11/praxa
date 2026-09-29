"""Chroma vector store.

PersistentClient, not Client - the default is in-memory and silently loses
everything on exit. The embedding model name is pinned in the collection
metadata and checked on every open, because vectors from two different models
are not comparable and mixing them degrades retrieval with no error message.
"""

from __future__ import annotations

from typing import Any

import chromadb
from pydantic import BaseModel

from career_copilot.core.config import get_settings
from career_copilot.core.errors import RetrievalError
from career_copilot.core.logging import get_logger
from career_copilot.rag.chunkers import Chunk
from career_copilot.rag.embeddings import get_embedder

__all__ = ["SearchHit", "VectorStore"]

log = get_logger(__name__)

COLLECTION_NAME = "career_kb"
ADD_BATCH_SIZE = 256


class SearchHit(BaseModel):
    doc_id: str
    text: str
    metadata: dict[str, Any]
    score: float  # 1.0 = identical, 0.0 = unrelated

    @property
    def citation(self) -> str:
        source = self.metadata.get("source", "unknown")
        section = self.metadata.get("section")
        return f"{source} - {section}" if section else str(source)


class VectorStore:
    def __init__(self, persist_dir: str | None = None) -> None:
        settings = get_settings()
        self._embedder = get_embedder()
        path = persist_dir or str(settings.chroma_dir)

        self._client = chromadb.PersistentClient(path=path)
        self._collection = self._client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={
                "hnsw:space": "cosine",
                "embedding_model": self._embedder.model_name,
            },
        )
        self._assert_model_matches()

    def _assert_model_matches(self) -> None:
        stored = (self._collection.metadata or {}).get("embedding_model")
        if stored and stored != self._embedder.model_name:
            raise RetrievalError(
                f"collection was built with {stored!r} but the configured model is "
                f"{self._embedder.model_name!r} - re-index before querying"
            )

    def count(self) -> int:
        return int(self._collection.count())

    def add(self, chunks: list[Chunk]) -> int:
        """Upsert chunks. IDs are deterministic, so re-ingesting replaces."""
        if not chunks:
            return 0

        for start in range(0, len(chunks), ADD_BATCH_SIZE):
            batch = chunks[start : start + ADD_BATCH_SIZE]
            try:
                self._collection.upsert(
                    ids=[f"{c.source}:{c.chunk_index}" for c in batch],
                    documents=[c.text for c in batch],
                    embeddings=self._embedder.embed_documents([c.text for c in batch]),
                    metadatas=[c.metadata() for c in batch],
                )
            except Exception as exc:  # chroma failures surface as retrieval failures
                raise RetrievalError(f"upsert failed: {type(exc).__name__}: {exc}") from exc

        log.info("indexed chunks", extra={"chunks": len(chunks), "total": self.count()})
        return len(chunks)

    def replace_document(self, source: str, chunks: list[Chunk]) -> int:
        """Swap one document's chunks, leaving every other document alone.

        The alternative - and what uploading a CV used to do - is `reset()` plus
        a full re-add: every document in the corpus re-chunked and re-embedded to
        change one file. On 25 documents that is minutes of work to save a
        two-page CV, and because `reset()` deletes and recreates the collection
        on a client Chroma shares process-wide, doing it twice in one process
        deadlocked.

        Chunk ids are `{source}:{index}`, so deleting by `source` removes exactly
        the old version - including its trailing chunks when the new document is
        shorter, which a plain upsert would silently leave behind.
        """
        try:
            self._collection.delete(where={"source": source})
        except Exception as exc:
            raise RetrievalError(f"could not remove {source}: {type(exc).__name__}: {exc}") from exc
        added = self.add(chunks)
        log.info("document replaced", extra={"source": source, "chunks": added})
        return added

    def remove_document(self, source: str) -> None:
        """Take one document out of the index."""
        try:
            self._collection.delete(where={"source": source})
        except Exception as exc:
            raise RetrievalError(f"could not remove {source}: {type(exc).__name__}: {exc}") from exc
        log.info("document removed from index", extra={"source": source})

    def all_documents(self) -> list[tuple[str, str, dict[str, Any]]]:
        """Everything indexed, as (id, text, metadata). Used to build the BM25 index."""
        result = self._collection.get()
        ids = result.get("ids") or []
        documents = result.get("documents") or []
        metadatas = result.get("metadatas") or []
        return [
            (str(i), str(d), dict(m or {}))
            for i, d, m in zip(ids, documents, metadatas, strict=False)
        ]

    def search(
        self,
        query: str,
        *,
        k: int = 5,
        where: dict[str, Any] | None = None,
    ) -> list[SearchHit]:
        """Similarity search with optional metadata filtering.

        `where` is the structured-retrieval hook: {"profile": "devops"} or
        {"$and": [{"doc_type": "resume"}, {"profile": "devops"}]}.
        """
        if self.count() == 0:
            raise RetrievalError("the knowledge base is empty - run ingestion first")

        try:
            result = self._collection.query(
                query_embeddings=[self._embedder.embed_query(query)],
                n_results=k,
                where=where,
            )
        except Exception as exc:  # chroma failures surface as retrieval failures
            raise RetrievalError(f"query failed: {type(exc).__name__}: {exc}") from exc

        ids = (result.get("ids") or [[]])[0]
        documents = (result.get("documents") or [[]])[0]
        metadatas = (result.get("metadatas") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]

        return [
            SearchHit(
                doc_id=str(doc_id),
                text=doc,
                metadata=dict(meta or {}),
                score=max(0.0, 1.0 - float(dist)),
            )
            for doc_id, doc, meta, dist in zip(ids, documents, metadatas, distances, strict=False)
        ]

    def reset(self) -> None:
        """Delete and recreate the collection - used when re-indexing from scratch."""
        self._client.delete_collection(COLLECTION_NAME)
        self._collection = self._client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={
                "hnsw:space": "cosine",
                "embedding_model": self._embedder.model_name,
            },
        )
        log.info("collection reset")
