"""Markdown to .docx, ATS-safe by construction.

Recruiters and applicant tracking systems want Word files. The tools generate
Markdown because that is what a language model produces reliably; this converts
it, and does so under the same rules the ATS guide in the knowledge base states:

- **Single column, no tables, no text boxes, no images.** Every one of those is
  a documented parser failure. A two-column CV frequently arrives at the ATS as
  interleaved nonsense.
- **Real heading styles**, not bold text pretending to be a heading, so the
  document has a structure a parser can read.
- **A common font.** Anything exotic risks substitution, and substitution
  shifts layout.

The converter is deliberately small. It handles the subset of Markdown the
generators actually emit - headings, bullets, bold - and treats anything else as
a paragraph. A fuller Markdown parser would add a dependency and new failure
modes to solve a problem we do not have.
"""

from __future__ import annotations

import re
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt

from career_copilot.core.errors import DocumentError
from career_copilot.core.logging import get_logger

__all__ = ["markdown_to_docx"]

log = get_logger(__name__)

BODY_FONT = "Calibri"
BODY_SIZE_PT = 11

_HEADING = re.compile(r"^(#{1,4})\s+(.*)$")
_BULLET = re.compile(r"^\s*[-*+]\s+(.*)$")
_NUMBERED = re.compile(r"^\s*\d+[.)]\s+(.*)$")
_BOLD_SPLIT = re.compile(r"(\*\*[^*]+\*\*)")
_INLINE_CODE = re.compile(r"`([^`]*)`")


def _add_runs(paragraph: object, text: str) -> None:
    """Write text into a paragraph, honouring **bold** and stripping `code`.

    Backticks are removed rather than rendered as a monospace run: a CV with
    code formatting in it looks like a mistake to a recruiter, and the ATS does
    not care either way.
    """
    clean = _INLINE_CODE.sub(r"\1", text)
    for fragment in _BOLD_SPLIT.split(clean):
        if not fragment:
            continue
        if fragment.startswith("**") and fragment.endswith("**"):
            run = paragraph.add_run(fragment[2:-2])  # type: ignore[attr-defined]
            run.bold = True
        else:
            paragraph.add_run(fragment)  # type: ignore[attr-defined]


def markdown_to_docx(markdown: str, path: Path, *, title: str | None = None) -> Path:
    """Write `markdown` to `path` as a Word document. Returns the path.

    Raises:
        DocumentError: the file could not be written.
    """
    document = Document()

    normal = document.styles["Normal"]
    normal.font.name = BODY_FONT
    normal.font.size = Pt(BODY_SIZE_PT)
    normal.paragraph_format.space_after = Pt(6)

    if title:
        document.core_properties.title = title

    for raw_line in markdown.splitlines():
        line = raw_line.rstrip()

        if not line.strip():
            continue  # blank lines are spacing, and spacing is the style's job

        if line.strip() in {"---", "***", "___"}:
            document.add_paragraph()
            continue

        heading = _HEADING.match(line)
        if heading:
            level = len(heading.group(1))
            paragraph = document.add_heading(level=min(level, 4))
            _add_runs(paragraph, heading.group(2))
            continue

        bullet = _BULLET.match(line)
        if bullet:
            paragraph = document.add_paragraph(style="List Bullet")
            _add_runs(paragraph, bullet.group(1))
            continue

        numbered = _NUMBERED.match(line)
        if numbered:
            paragraph = document.add_paragraph(style="List Number")
            _add_runs(paragraph, numbered.group(1))
            continue

        paragraph = document.add_paragraph()
        paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
        _add_runs(paragraph, line.strip())

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        document.save(str(path))
    except OSError as exc:
        raise DocumentError(f"could not write {path}: {exc}") from exc

    log.info("docx written", extra={"path": str(path)})
    return path
