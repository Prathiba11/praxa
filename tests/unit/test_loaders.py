import pytest

from career_copilot.core.errors import IngestionError
from career_copilot.core.types import DocType, Profile
from career_copilot.rag.loaders import discover, load_all, load_document

RESUME = """# Prathiba Prabhakaran
## Summary
Automotive cybersecurity engineer.
## Skills
- ISO/SAE 21434
"""

GUIDE = """# ATS Guide
## Parse safety
Single column, no tables.
"""

DOMAIN = """# ISO/SAE 21434
## TARA
Asset identification, threat scenarios, impact rating.
"""


@pytest.fixture
def kb(tmp_path):
    """A miniature knowledge base with all three layouts."""
    (tmp_path / "kb" / "guides").mkdir(parents=True)
    (tmp_path / "kb" / "domain" / "automotive_cyber").mkdir(parents=True)
    (tmp_path / "data" / "kb" / "resumes").mkdir(parents=True)

    (tmp_path / "kb" / "guides" / "ats_guide.md").write_text(GUIDE, encoding="utf-8")
    (tmp_path / "kb" / "domain" / "automotive_cyber" / "iso.md").write_text(
        DOMAIN, encoding="utf-8"
    )
    (tmp_path / "data" / "kb" / "resumes" / "automotive_cyber.md").write_text(
        RESUME, encoding="utf-8"
    )
    return tmp_path


def test_resume_metadata_inferred_from_filename(kb):
    doc = load_document(kb / "data" / "kb" / "resumes" / "automotive_cyber.md")
    assert doc.doc_type == DocType.RESUME
    assert doc.profile == Profile.AUTOMOTIVE_CYBER
    assert doc.source == "automotive_cyber.md"


def test_guide_has_no_profile(kb):
    doc = load_document(kb / "kb" / "guides" / "ats_guide.md")
    assert doc.doc_type == DocType.GUIDE
    assert doc.profile is None


def test_domain_profile_inferred_from_folder(kb):
    doc = load_document(kb / "kb" / "domain" / "automotive_cyber" / "iso.md")
    assert doc.doc_type == DocType.DOMAIN
    assert doc.profile == Profile.AUTOMOTIVE_CYBER


def test_unknown_location_is_rejected(tmp_path):
    stray = tmp_path / "notes.md"
    stray.write_text("# Notes\nsome text", encoding="utf-8")
    with pytest.raises(IngestionError):
        load_document(stray)


def test_empty_file_is_rejected(kb):
    empty = kb / "kb" / "guides" / "empty.md"
    empty.write_text("   \n", encoding="utf-8")
    with pytest.raises(IngestionError):
        load_document(empty)


def test_unfinished_document_is_rejected(kb):
    """The [[TODO guard: half-written content must not enter the index."""
    draft = kb / "kb" / "guides" / "draft.md"
    draft.write_text("# Draft\n\nReduced build time by [[TODO: how much?]].", encoding="utf-8")
    with pytest.raises(IngestionError, match="TODO"):
        load_document(draft)


def test_unknown_profile_folder_is_rejected(kb):
    bad = kb / "kb" / "domain" / "quantum_computing"
    bad.mkdir()
    (bad / "notes.md").write_text("# Notes\ncontent", encoding="utf-8")
    with pytest.raises(IngestionError):
        load_document(bad / "notes.md")


def test_discover_finds_everything_and_is_sorted(kb):
    found = discover(kb / "kb", kb / "data" / "kb" / "resumes")
    assert len(found) == 3

    kb_files = found[:2]  # kb/ files come first, resumes are appended after
    assert kb_files == sorted(kb_files)


def test_discover_raises_when_nothing_found(tmp_path):
    with pytest.raises(IngestionError):
        discover(tmp_path / "nope", tmp_path / "also-nope")


def test_load_all_returns_every_document(kb):
    docs = load_all(kb / "kb", kb / "data" / "kb" / "resumes")
    assert len(docs) == 3
    assert {d.doc_type for d in docs} == {DocType.RESUME, DocType.GUIDE, DocType.DOMAIN}


# ------------------------------------------------------------------ sample CVs


SAMPLE = """# Marek Duvall
_Sample CV. Marek Duvall is not a real person._
## Summary
Platform engineer.
"""


@pytest.fixture
def kb_with_samples(kb):
    """The same knowledge base, plus committed sample CVs."""
    samples = kb / "kb" / "resumes_sample"
    samples.mkdir()
    (samples / "devops.md").write_text(SAMPLE, encoding="utf-8")
    return kb


def test_a_sample_cv_loads_as_a_resume(kb_with_samples):
    """The folder is named differently; the document type is not."""
    doc = load_document(kb_with_samples / "kb" / "resumes_sample" / "devops.md")
    assert doc.doc_type == DocType.RESUME
    assert doc.profile == Profile.DEVOPS


def test_real_cvs_win_over_the_samples(kb_with_samples):
    """The whole point of the fallback is that it steps aside.

    Indexing both would put a real career and an invented one under the same
    profile, and the assistant would cite whichever the retriever happened to
    rank - which is the one failure this application must not have.
    """
    found = discover(kb_with_samples / "kb", kb_with_samples / "data" / "kb" / "resumes")

    assert not any("resumes_sample" in path.parts for path in found)
    assert any(path.name == "automotive_cyber.md" for path in found)


def test_the_samples_are_used_when_there_are_no_real_cvs(kb_with_samples, tmp_path):
    """What a reviewer gets after cloning: real CVs are gitignored, so absent."""
    empty = tmp_path / "no-resumes-here"
    empty.mkdir()

    found = discover(kb_with_samples / "kb", empty)

    assert any("resumes_sample" in path.parts for path in found)
    docs = load_all(kb_with_samples / "kb", empty)
    assert any(d.doc_type == DocType.RESUME and d.profile == Profile.DEVOPS for d in docs)
