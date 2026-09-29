"""Growing the knowledge base from the browser.

The corpus shipped with this project is small on purpose - fourteen documents,
enough to demonstrate retrieval and small enough to reason about. It is also the
project's most honest limitation: on a corpus this size the first search usually
finds the right file, which is why the grading loop only fires on five of
twenty-eight evaluation questions.

This router is how it stops being fixed. A person adds their own material -
notes on a standard, a guide they wrote, a domain they work in - and it becomes
searchable alongside everything else.

**Where an uploaded document goes decides what it is.** The loader infers a
document's type and profile from its path: `kb/domain/<profile>/` is domain
knowledge for that career, `kb/guides/` is advice that belongs to no profile.
Nothing here writes metadata into the file, because a second source of truth
about what a document is would eventually disagree with the first.

**Only documents added here can be deleted here.** The files that came with the
project are reference material for a submitted piece of work, and a DELETE that
could reach them would turn one mis-click into a lost corpus. Every upload is
recorded in a manifest, and delete refuses anything the manifest does not name.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import Field

from career_copilot.api.schemas import Camel, ProfileValue
from career_copilot.core.config import get_settings
from career_copilot.core.errors import CopilotError
from career_copilot.core.logging import get_logger
from career_copilot.rag.loaders import load_all
from career_copilot.rag.reindex import rebuild_index

__all__ = ["router"]

log = get_logger(__name__)

router = APIRouter(tags=["knowledge"], prefix="/knowledge")

_MIN_CHARS = 200
_MAX_CHARS = 400_000
_SLUG = re.compile(r"[^a-z0-9]+")


def _kb_root() -> Path:
    """Where the loader looks. Repo-relative, like `loaders.discover`."""
    return Path("kb")


def _manifest_path() -> Path:
    path = get_settings().data_dir / "kb"
    path.mkdir(parents=True, exist_ok=True)
    return path / "added.json"


def _manifest() -> dict[str, str]:
    path = _manifest_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        # A corrupt manifest must not make the whole library unreadable. The
        # cost of losing it is that user documents become undeletable here, not
        # that anything is lost from the index.
        log.warning("knowledge manifest is unreadable - treating it as empty")
        return {}
    return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}


def _write_manifest(entries: dict[str, str]) -> None:
    _manifest_path().write_text(json.dumps(entries, indent=2, sort_keys=True), encoding="utf-8")


def _slugify(title: str) -> str:
    slug = _SLUG.sub("_", title.strip().lower()).strip("_")
    return slug[:60] or "document"


class KnowledgeUpload(Camel):
    title: str = Field(min_length=3, max_length=120)
    #: A profile makes it domain knowledge for that career; omitting it makes it
    #: a guide, which every profile can retrieve.
    profile: ProfileValue | None = None
    content: str = Field(min_length=_MIN_CHARS, max_length=_MAX_CHARS)


class KnowledgeDoc(Camel):
    source: str
    doc_type: str
    profile: str | None
    characters: int
    #: False for the documents that shipped with the project. Those cannot be
    #: deleted from here, and the UI greys the button rather than failing later.
    removable: bool


class IndexResult(Camel):
    documents: int
    chunks: int
    message: str


@router.get("", response_model=list[KnowledgeDoc])
def list_knowledge() -> list[KnowledgeDoc]:
    """Everything currently indexed, and which of it you added."""
    added = _manifest()
    try:
        documents = load_all()
    except CopilotError as exc:
        raise HTTPException(status_code=500, detail=exc.user_message) from exc

    return [
        KnowledgeDoc(
            source=doc.source,
            doc_type=str(doc.doc_type),
            profile=str(doc.profile) if doc.profile else None,
            characters=len(doc.text),
            removable=doc.source in added,
        )
        for doc in documents
    ]


@router.post("", response_model=IndexResult, status_code=201)
def add_knowledge(payload: KnowledgeUpload) -> IndexResult:
    """Add a document and make it searchable."""
    text = payload.content.strip()
    if not text:
        raise HTTPException(status_code=400, detail="That file had no text in it.")

    if payload.profile:
        directory = _kb_root() / "domain" / payload.profile
    else:
        directory = _kb_root() / "guides"
    directory.mkdir(parents=True, exist_ok=True)

    name = f"{_slugify(payload.title)}.md"
    path = directory / name
    if path.exists() and name not in _manifest():
        # Overwriting a document that shipped with the project would be a silent
        # edit to the corpus an evaluation was measured against.
        raise HTTPException(
            status_code=409,
            detail=f"'{name}' already exists in the knowledge base. Give this one a different title.",
        )

    existed = path.read_text(encoding="utf-8") if path.is_file() else None
    path.write_text(f"# {payload.title.strip()}\n\n{text}\n", encoding="utf-8")

    try:
        documents, chunks = rebuild_index()
    except CopilotError as exc:
        if existed is None:
            path.unlink(missing_ok=True)
        else:
            path.write_text(existed, encoding="utf-8")
        log.warning("knowledge upload failed to index", extra={"detail": exc.detail})
        raise HTTPException(status_code=400, detail=exc.user_message) from exc

    entries = _manifest()
    entries[name] = str(path)
    _write_manifest(entries)

    log.info("knowledge document added", extra={"source": name, "chunks": chunks})
    return IndexResult(
        documents=documents,
        chunks=chunks,
        message=f"Added. {chunks} passages from {documents} documents are now searchable.",
    )


@router.delete("/{source}", response_model=IndexResult)
def remove_knowledge(source: str) -> IndexResult:
    """Remove a document you added. Refuses anything that shipped with the project."""
    entries = _manifest()
    if source not in entries:
        raise HTTPException(
            status_code=404,
            detail="That document was not added here, so it cannot be removed here.",
        )

    Path(entries[source]).unlink(missing_ok=True)
    del entries[source]
    _write_manifest(entries)

    documents, chunks = rebuild_index()
    log.info("knowledge document removed", extra={"source": source, "chunks": chunks})
    return IndexResult(
        documents=documents,
        chunks=chunks,
        message=f"Removed. {chunks} passages from {documents} documents remain.",
    )
