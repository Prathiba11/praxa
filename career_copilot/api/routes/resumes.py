"""Putting your own CV in, from the browser.

Until now the knowledge base was whatever sat in `data/kb/resumes/` on disk, put
there by hand and indexed by a script. That made the application honest but
personal: it answered questions about *one* engineer, and anyone else looking at
it was looking at a demo.

This router is the smallest change that fixes that. A CV arrives as text, it
replaces the file for its profile, and the index is rebuilt - after which every
part of the system that reads a CV reads the new one: retrieval, fit scoring, CV
tailoring, cover letters, interview practice.

**Text rather than a file upload.** FastAPI needs `python-multipart` for
`UploadFile`, and the loader only ever reads `.md`. Sending the content as text
skips a dependency for a capability nothing downstream could use: a .docx
arriving here would have to be converted to Markdown before indexing anyway. The
browser reads the file and posts what it found.

**Why the whole index is rebuilt.** Replacing one CV should remove the chunks of
the CV it replaced, and the vector store deletes by collection rather than by
document. Rebuilding 166 chunks against an already-warm embedder takes a few
seconds and is obviously correct; a partial update that left the previous CV's
chunks behind would answer questions about two different people and look fine
doing it. The cost is real and stated - it is why this is a deliberate button
and not something that happens on every keystroke.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import cast, get_args

from fastapi import APIRouter, HTTPException
from pydantic import Field

from career_copilot.api.schemas import Camel, ProfileValue
from career_copilot.core.config import get_settings
from career_copilot.core.errors import CopilotError
from career_copilot.core.logging import get_logger
from career_copilot.core.types import Profile
from career_copilot.rag.chunkers import chunk_documents
from career_copilot.rag.loaders import load_all, load_document
from career_copilot.rag.store import VectorStore

__all__ = ["router"]

log = get_logger(__name__)

router = APIRouter(tags=["resumes"], prefix="/resumes")

#: A CV is a document, not a corpus. Ten megabytes of "CV" is either a mistake
#: or something that is not a CV, and either way it should not reach the indexer.
_MAX_CHARS = 200_000
_MIN_CHARS = 200


class ResumeUpload(Camel):
    profile: ProfileValue
    #: What the browser called the file, kept for logging only. The name on disk
    #: is the profile for a tracked track, and a slug of the document's own
    #: heading on the General shelf - never this, because a browser-supplied
    #: name is untrusted input and would be a path to sanitise.
    filename: str = Field(default="", max_length=200)
    content: str = Field(min_length=_MIN_CHARS, max_length=_MAX_CHARS)


class ResumeOut(Camel):
    profile: ProfileValue
    #: Identifies one row. For a tracked profile it is the profile name, because
    #: there is exactly one CV. On the General shelf it is the file's stem, so
    #: several rows can share a profile and still be addressed individually.
    id: str
    #: What to show. Taken from the document's first heading where there is one,
    #: because "General" on four rows tells the reader nothing.
    label: str
    #: False means the sample CV is standing in - a fictional person, which the
    #: user needs to know before they trust an answer about "their" experience.
    is_yours: bool
    characters: int
    updated_at: datetime | None
    #: True for the General CV that `load_resume` would pick right now. Exactly
    #: one row can carry it, and the interface says so rather than leaving the
    #: user to guess which of several is in use.
    in_use: bool = False


class IndexResult(Camel):
    profile: ProfileValue
    documents: int
    chunks: int
    message: str


def _value(profile: Profile) -> ProfileValue:
    """`Profile` is a StrEnum; `ProfileValue` is the Literal the API promises.

    They carry the same three strings and mypy cannot see that, which is what the
    two `# type: ignore` comments here used to paper over. Narrowing once, in a
    function that fails loudly on an unknown member, is the same assertion made
    where it can be checked - and it is the thing that will break first if a
    fourth profile is added without updating the API's type.
    """
    value = str(profile)
    if value not in get_args(ProfileValue):
        raise ValueError(f"profile {value!r} is not in the API's ProfileValue")
    return cast(ProfileValue, value)


#: Shown when a tracked profile has no CV yet and so has no heading to read a
#: name from. The General shelf never needs one - an empty shelf has no rows.
PROFILE_LABELS: dict[Profile, str] = {
    Profile.AUTOMOTIVE_CYBER: "Automotive cybersecurity",
    Profile.DEVOPS: "DevOps",
    Profile.AI_ENG: "AI engineering",
    Profile.GENERAL: "General",
}

_HEADING = re.compile(r"^#\s+(.+?)\s*$", re.M)


def _label_for(text: str, fallback: str) -> str:
    """The document's first heading, or the file name if it has none.

    A CV almost always opens with the person's name as an H1, which is a far
    better row label than a slug. Trimmed because a heading is free text and a
    200-character one would break the layout.
    """
    match = _HEADING.search(text)
    if match is None:
        return fallback
    return match.group(1).strip()[:60] or fallback


def _slug(text: str, fallback: str) -> str:
    """A file name derived from the document's own heading.

    Keeps the shelf legible on disk, which matters because these are the user's
    files: a folder of `cv-1.md`, `cv-2.md` is a folder nobody can tidy.
    """
    base = re.sub(r"[^a-z0-9]+", "-", _label_for(text, fallback).lower()).strip("-")
    return base[:48] or fallback


def _general_dir() -> Path:
    path = _resume_dir() / str(Profile.GENERAL)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _resume_dir() -> Path:
    path = get_settings().data_dir / "kb" / "resumes"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _has_real_cvs() -> bool:
    """Whether any CV of the user's own is on disk.

    This decides between the two reindex paths below, because it is the one
    change that is not local to a single file: the loader drops the sample CVs
    the moment a real one appears, and brings them back when the last one goes.
    """
    directory = _resume_dir()
    return bool(list(directory.glob("*.md")) or list((directory / "general").glob("*.md")))


def _reindex() -> tuple[int, int]:
    """Rebuild the whole index. Returns (documents, chunks).

    Kept for the transitions that genuinely change the whole corpus - the first
    real CV arriving, or the last one leaving, either of which swaps the sample
    CVs in or out. Everything else uses `_reindex_one`.
    """
    documents = load_all()
    chunks = chunk_documents(documents)
    store = VectorStore()
    store.reset()
    store.add(chunks)
    return len(documents), len(chunks)


def _reindex_one(path: Path) -> tuple[int, int]:
    """Re-index a single file. Returns (documents, chunks) for that file alone.

    Replacing one CV used to rebuild the entire index: 25 documents re-chunked
    and re-embedded to save a two-page file, which is why an upload took
    minutes. It also called `reset()`, which deletes and recreates the
    collection on a client Chroma shares across the process - doing that twice
    in one process deadlocked, as the shelf tests found.
    """
    document = load_document(path)
    chunks = chunk_documents([document])
    VectorStore().replace_document(document.source, chunks)
    return 1, len(chunks)


def _drop_one(path: Path) -> None:
    """Take a deleted file's chunks out without touching anything else."""
    VectorStore().remove_document(path.name)


def _row(path: Path, profile: Profile, fallback: str) -> ResumeOut:
    text = path.read_text(encoding="utf-8", errors="replace")
    return ResumeOut(
        profile=_value(profile),
        id=path.stem,
        label=_label_for(text, fallback),
        is_yours=True,
        characters=len(text),
        updated_at=datetime.fromtimestamp(path.stat().st_mtime, UTC),
    )


@router.get("", response_model=list[ResumeOut])
def list_resumes() -> list[ResumeOut]:
    """One row per tracked profile, then every CV on the General shelf.

    The shelf is returned newest first, and the newest carries `in_use` -
    `load_resume` picks by modification time, so the interface can state which
    document a General tailoring would actually read instead of implying that
    all of them are somehow in play.
    """
    directory = _resume_dir()
    out: list[ResumeOut] = []

    for profile in Profile:
        if profile is Profile.GENERAL:
            continue
        path = directory / f"{profile}.md"
        label = PROFILE_LABELS[profile]
        if path.is_file():
            out.append(_row(path, profile, label))
        else:
            out.append(
                ResumeOut(
                    profile=_value(profile),
                    id=str(profile),
                    label=label,
                    is_yours=False,
                    characters=0,
                    updated_at=None,
                )
            )

    shelf = sorted(_general_dir().glob("*.md"), key=lambda item: item.stat().st_mtime, reverse=True)
    for index, path in enumerate(shelf):
        row = _row(path, Profile.GENERAL, path.stem)
        row.in_use = index == 0
        out.append(row)

    return out


def _destination(profile: Profile, text: str) -> Path:
    """Where an uploaded CV lands.

    A tracked profile has exactly one CV, so an upload replaces it. General is a
    shelf, so an upload adds to it - and the file is named after the document's
    own heading, which means uploading the same CV twice overwrites rather than
    accumulating near-duplicates nobody can tell apart.
    """
    if profile is not Profile.GENERAL:
        return _resume_dir() / f"{profile}.md"
    return _general_dir() / f"{_slug(text, 'cv')}.md"


@router.post("", response_model=IndexResult, status_code=201)
def upload_resume(payload: ResumeUpload) -> IndexResult:
    """Add or replace a CV and rebuild the index."""
    text = payload.content.strip()
    if not text:
        raise HTTPException(status_code=400, detail="That file had no text in it.")

    path = _destination(Profile(payload.profile), text)
    previous = path.read_text(encoding="utf-8") if path.is_file() else None
    # Captured before the write: if this is the first real CV, the loader is
    # about to drop every sample from the corpus, and only a full rebuild
    # reflects that. Any later upload changes one file and nothing else.
    was_empty = not _has_real_cvs()
    path.write_text(text, encoding="utf-8")

    try:
        documents, chunks = _reindex() if was_empty else _reindex_one(path)
    except CopilotError as exc:
        # Put back whatever was there. A half-applied upload would leave the
        # user with a CV on disk that nothing had indexed, and no way to tell.
        if previous is None:
            path.unlink(missing_ok=True)
        else:
            path.write_text(previous, encoding="utf-8")
        log.warning("resume upload failed to index", extra={"detail": exc.detail})
        raise HTTPException(status_code=500, detail=exc.user_message) from exc

    log.info(
        "resume saved and indexed",
        extra={
            "profile": payload.profile,
            "chunks": chunks,
            "characters": len(text),
            "full_rebuild": was_empty,
        },
    )
    message = (
        f"Indexed {chunks} passages from {documents} documents."
        if was_empty
        else f"Saved. {chunks} passages indexed from this CV; the rest of the index was untouched."
    )
    return IndexResult(profile=payload.profile, documents=documents, chunks=chunks, message=message)


@router.delete("/general/{resume_id}", response_model=IndexResult)
def remove_general_resume(resume_id: str) -> IndexResult:
    """Remove one CV from the General shelf.

    Declared before `/{profile}`: FastAPI matches in order, and `general` would
    otherwise be caught by the profile route and delete the wrong thing.
    """
    path = _general_dir() / f"{resume_id}.md"
    # Rebuilt from the id rather than trusted: a path segment arrives from the
    # network, and `..%2Fdevops` would otherwise reach outside the shelf and
    # delete a tracked CV. Resolving and comparing parents is the check.
    if path.resolve().parent != _general_dir().resolve() or not path.is_file():
        raise HTTPException(status_code=404, detail="There is no CV on the shelf with that name.")

    path.unlink()
    # A full rebuild only when the last real CV has just gone, because the
    # samples have to come back into the corpus.
    if _has_real_cvs():
        _drop_one(path)
        documents, chunks = 0, 0
        message = "Removed. The rest of the index was untouched."
    else:
        documents, chunks = _reindex()
        message = f"Removed. The sample CVs are standing in again; {chunks} passages indexed."
    log.info("general CV removed", extra={"id": resume_id})
    return IndexResult(profile="general", documents=documents, chunks=chunks, message=message)


@router.delete("/{profile}", response_model=IndexResult)
def remove_resume(profile: ProfileValue) -> IndexResult:
    """Take your CV back out. The sample stands in again."""
    path = _resume_dir() / f"{profile}.md"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="There is no CV stored for that profile.")

    path.unlink()
    if _has_real_cvs():
        _drop_one(path)
        documents, chunks = 0, 0
        message = "Removed. The rest of the index was untouched."
    else:
        documents, chunks = _reindex()
        message = f"Removed. The sample CVs are standing in again; {chunks} passages indexed."
    log.info("resume removed", extra={"profile": profile})
    return IndexResult(profile=profile, documents=documents, chunks=chunks, message=message)
