"""Rebuilding the index after the knowledge base changes.

Two routers change what is on disk - a CV being replaced, a document being
added - and both have to make the vector store agree with the files again.

**It rebuilds everything rather than updating one document.** The store deletes
by collection, not by document, so removing just the passages that came from one
file is not an operation it offers. A partial update would therefore leave the
old file's passages in place beside the new ones, and the assistant would answer
from both without anything looking wrong - the failure this application most
needs to avoid, since one of those documents would be a CV describing a
different career.

The cost is a few seconds against an already-warm embedder, which is why both
callers are deliberate actions a person takes, not something that happens while
they type.
"""

from __future__ import annotations

from career_copilot.core.logging import get_logger
from career_copilot.rag.chunkers import chunk_documents
from career_copilot.rag.loaders import load_all
from career_copilot.rag.store import VectorStore

__all__ = ["rebuild_index"]

log = get_logger(__name__)


def rebuild_index() -> tuple[int, int]:
    """Re-read the knowledge base and replace the index. Returns (documents, chunks)."""
    documents = load_all()
    chunks = chunk_documents(documents)
    store = VectorStore()
    store.reset()
    added = store.add(chunks)
    log.info("index rebuilt", extra={"documents": len(documents), "chunks": added})
    return len(documents), added
