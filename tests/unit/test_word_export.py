"""Markdown to .docx.

The conversion is small, so the tests are about the rules it has to keep rather
than about coverage: real heading styles, real list styles, no tables, and a
readable body font. Those are the things the ATS guide says decide whether a
parser can read the document at all.
"""

from __future__ import annotations

import pytest
from docx import Document

from career_copilot.documents import markdown_to_docx

_CV = """# Prathiba Prabhakaran

## Summary

Platform engineer with **six years** of experience.

## Experience

- Operated Kubernetes clusters
- Reduced pipeline build time

## Gaps against this posting

- No production Rust
"""


def _written(tmp_path, markdown: str):
    path = markdown_to_docx(markdown, tmp_path / "out.docx", title="Test CV")
    return Document(str(path))


def test_a_file_is_produced(tmp_path):
    path = markdown_to_docx(_CV, tmp_path / "cv.docx")
    assert path.exists()
    assert path.stat().st_size > 0


def test_headings_become_real_heading_styles(tmp_path):
    """Bold text pretending to be a heading gives the parser no structure."""
    document = _written(tmp_path, _CV)
    headings = [p.text for p in document.paragraphs if p.style.name.startswith("Heading")]
    assert "Summary" in headings
    assert "Experience" in headings


def test_bullets_become_real_list_items(tmp_path):
    document = _written(tmp_path, _CV)
    bullets = [p.text for p in document.paragraphs if p.style.name == "List Bullet"]
    assert "Operated Kubernetes clusters" in bullets


def test_numbered_lists_are_recognised(tmp_path):
    document = _written(tmp_path, "1. First step\n2. Second step\n")
    numbered = [p.text for p in document.paragraphs if p.style.name == "List Number"]
    assert numbered == ["First step", "Second step"]


def test_bold_markers_are_applied_not_printed(tmp_path):
    document = _written(tmp_path, _CV)
    text = "\n".join(p.text for p in document.paragraphs)
    assert "**" not in text
    assert any(run.bold for p in document.paragraphs for run in p.runs)


def test_inline_code_backticks_are_stripped(tmp_path):
    """A CV with code formatting in it reads as a mistake to a recruiter."""
    document = _written(tmp_path, "Worked with `Kubernetes` daily.\n")
    text = " ".join(p.text for p in document.paragraphs)
    assert "`" not in text
    assert "Kubernetes" in text


def test_no_tables_are_ever_produced(tmp_path):
    """Tables are the single most common ATS parsing failure."""
    document = _written(tmp_path, _CV)
    assert document.tables == []


def test_the_body_font_is_a_common_one(tmp_path):
    """An exotic font risks substitution, and substitution shifts layout."""
    document = _written(tmp_path, _CV)
    assert document.styles["Normal"].font.name == "Calibri"


def test_the_title_is_stored_in_the_document_properties(tmp_path):
    path = markdown_to_docx(_CV, tmp_path / "cv.docx", title="Tailored CV")
    assert Document(str(path)).core_properties.title == "Tailored CV"


def test_horizontal_rules_do_not_become_literal_dashes(tmp_path):
    document = _written(tmp_path, "Above\n\n---\n\nBelow\n")
    text = " ".join(p.text for p in document.paragraphs)
    assert "---" not in text
    assert "Above" in text
    assert "Below" in text


def test_empty_input_produces_an_empty_but_valid_document(tmp_path):
    path = markdown_to_docx("", tmp_path / "empty.docx")
    assert path.exists()
    assert [p.text for p in Document(str(path)).paragraphs if p.text.strip()] == []


def test_a_bad_destination_is_a_typed_error(tmp_path):
    from career_copilot.core.errors import DocumentError

    blocker = tmp_path / "not-a-directory"
    blocker.write_text("i am a file", encoding="utf-8")

    with pytest.raises(DocumentError):
        markdown_to_docx(_CV, blocker / "cv.docx")
