"""Per-document-type chunking.

One strategy does not fit all three document types:

- Resumes are structured records. Split on section headings, and within
  Experience on each role, so a retrieved chunk is one coherent unit. Never
  split a bullet - a fragment like "reducing findings by 60%" with no context
  is useless when retrieved.
- Guides and domain notes are prose. Recursive character splitting respecting
  paragraph boundaries, with overlap so meaning is not cut at a seam.
"""

from __future__ import annotations

import re

from langchain_text_splitters import RecursiveCharacterTextSplitter
from pydantic import BaseModel

from career_copilot.core.logging import get_logger
from career_copilot.core.types import DocType, Profile
from career_copilot.rag.loaders import RawDocument

__all__ = ["Chunk", "chunk_document", "chunk_documents"]

log = get_logger(__name__)

PROSE_CHUNK_CHARS = 900
PROSE_OVERLAP_CHARS = 150
RESUME_MAX_CHARS = 1200
MIN_CHUNK_CHARS = 120
MIN_RESUME_CHUNK_CHARS = 40

_H2 = re.compile(r"^## +(.+)$", re.MULTILINE)
_H3 = re.compile(r"^### +(.+)$", re.MULTILINE)


class Chunk(BaseModel):
    text: str
    doc_type: DocType
    profile: Profile | None
    source: str
    section: str | None
    chunk_index: int

    def metadata(self) -> dict[str, str | int]:
        """Chroma accepts primitives only - None values are dropped."""
        meta: dict[str, str | int] = {
            "doc_type": str(self.doc_type),
            "source": self.source,
            "chunk_index": self.chunk_index,
        }
        if self.profile:
            meta["profile"] = str(self.profile)
        if self.section:
            meta["section"] = self.section
        return meta


def _split_on(pattern: re.Pattern[str], text: str) -> list[tuple[str | None, str]]:
    """Split text into (heading, body) pairs at each heading match."""
    matches = list(pattern.finditer(text))
    if not matches:
        return [(None, text)]

    sections: list[tuple[str | None, str]] = []
    if matches[0].start() > 0:
        preamble = text[: matches[0].start()].strip()
        if preamble:
            sections.append((None, preamble))

    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[match.start() : end].strip()
        if body:
            sections.append((match.group(1).strip(), body))
    return sections


def _split_long_section(text: str, max_chars: int) -> list[str]:
    """Break an oversized section on bullet boundaries, never mid-bullet."""
    if len(text) <= max_chars:
        return [text]

    lines = text.splitlines()
    parts: list[str] = []
    current: list[str] = []
    size = 0

    for line in lines:
        starts_bullet = line.lstrip().startswith(("- ", "* ", "1."))
        if current and starts_bullet and size + len(line) > max_chars:
            parts.append("\n".join(current).strip())
            current, size = [], 0
        current.append(line)
        size += len(line) + 1

    if current:
        parts.append("\n".join(current).strip())
    return [p for p in parts if p]


def _chunk_resume(doc: RawDocument) -> list[str]:
    """Section-aware, with Experience split per role."""
    pieces: list[str] = []
    for heading, body in _split_on(_H2, doc.text):
        if heading and heading.lower().startswith(("experience", "projects")):
            for _, role_body in _split_on(_H3, body):
                pieces.extend(_split_long_section(role_body, RESUME_MAX_CHARS))
        else:
            pieces.extend(_split_long_section(body, RESUME_MAX_CHARS))
    return pieces


def _chunk_prose(doc: RawDocument) -> list[str]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=PROSE_CHUNK_CHARS,
        chunk_overlap=PROSE_OVERLAP_CHARS,
        separators=["\n## ", "\n### ", "\n\n", "\n", ". ", " ", ""],
    )
    return splitter.split_text(doc.text)


def _section_of(text: str) -> str | None:
    """First heading in the chunk, used for citations."""
    for pattern in (_H3, _H2):
        match = pattern.search(text)
        if match:
            return match.group(1).strip()
    return None


def chunk_document(doc: RawDocument) -> list[Chunk]:
    texts = _chunk_resume(doc) if doc.doc_type == DocType.RESUME else _chunk_prose(doc)
    min_chars = MIN_RESUME_CHUNK_CHARS if doc.doc_type == DocType.RESUME else MIN_CHUNK_CHARS
    kept = [
        t for t in texts if t.strip() and not _is_heading_only(t) and len(t.strip()) >= min_chars
    ]

    chunks: list[Chunk] = []
    current_section: str | None = None

    for index, text in enumerate(kept):
        heading = _section_of(text)
        if heading:
            current_section = heading
        # Continuation pieces inherit the heading they belong under, so a
        # citation reads "ats_guide.md - Keyword strategy" rather than bare.
        chunks.append(
            Chunk(
                text=text,
                doc_type=doc.doc_type,
                profile=doc.profile,
                source=doc.source,
                section=current_section,
                chunk_index=index,
            )
        )
    return chunks


def chunk_documents(docs: list[RawDocument]) -> list[Chunk]:
    chunks = [c for doc in docs for c in chunk_document(doc)]
    log.info("chunked knowledge base", extra={"documents": len(docs), "chunks": len(chunks)})
    return chunks


def _is_heading_only(text: str) -> bool:
    """A piece containing nothing but a heading carries no retrievable content."""
    lines = [line for line in text.strip().splitlines() if line.strip()]
    return len(lines) == 1 and lines[0].lstrip().startswith("#")
