import re

from career_copilot.core.types import DocType, Profile
from career_copilot.rag.chunkers import PROSE_CHUNK_CHARS, chunk_document, chunk_documents
from career_copilot.rag.loaders import RawDocument

RESUME_TEXT = """# Prathiba Prabhakaran
Automotive Cybersecurity Engineer

## Summary
Cybersecurity consultant with four years of experience.

## Skills
- Standards: ISO/SAE 21434, TARA, CSMS
- Testing: grey-box penetration testing, CAN analysis

## Experience

### Cybersecurity Consultant - Vector Consulting Services GmbH
Stuttgart, Germany - 07/2022 - 06/2026
- Delivered TARA per ISO/SAE 21434 across multiple customer platforms.
- Supported CSMS introduction across five to ten customers.

### Software Developer - L&T Technology Services Limited
India - 08/2015 - 08/2016
- Developed middleware for UNITRAX using EGL and RBD.

## Education

### M.Sc. Information Technology - University of Stuttgart
Stuttgart, Germany - 2018 - 2022
"""


def _resume() -> RawDocument:
    return RawDocument(
        text=RESUME_TEXT,
        doc_type=DocType.RESUME,
        profile=Profile.AUTOMOTIVE_CYBER,
        source="automotive_cyber.md",
        source_path="data/kb/resumes/automotive_cyber.md",
    )


def _prose(text: str) -> RawDocument:
    return RawDocument(
        text=text,
        doc_type=DocType.DOMAIN,
        profile=Profile.DEVOPS,
        source="kubernetes.md",
        source_path="kb/domain/devops/kubernetes.md",
    )


def test_resume_produces_a_chunk_per_section():
    chunks = chunk_document(_resume())
    assert len(chunks) >= 4


def test_each_experience_role_is_its_own_chunk():
    chunks = chunk_document(_resume())
    texts = [c.text for c in chunks]
    vector = [t for t in texts if "Vector Consulting" in t]
    lt = [t for t in texts if "L&T Technology" in t]

    assert len(vector) == 1
    assert len(lt) == 1
    assert "L&T Technology" not in vector[0], "roles must not share a chunk"


def test_no_bullet_is_split_across_chunks():
    """The invariant the whole resume strategy depends on."""
    chunks = chunk_document(_resume())
    combined = chunks  # each source bullet must appear whole in exactly one chunk

    for line in RESUME_TEXT.splitlines():
        bullet = line.strip()
        if not bullet.startswith("- "):
            continue
        containing = [c for c in combined if bullet in c.text]
        assert len(containing) == 1, f"bullet appears in {len(containing)} chunks: {bullet!r}"


def test_long_section_splits_only_on_bullet_boundaries():
    long_resume = "## Experience\n\n### Role - Company\n" + "\n".join(
        f"- Achievement number {i} with enough words to make this line reasonably long."
        for i in range(60)
    )
    doc = RawDocument(
        text=long_resume,
        doc_type=DocType.RESUME,
        profile=Profile.DEVOPS,
        source="devops.md",
        source_path="data/kb/resumes/devops.md",
    )
    chunks = chunk_document(doc)

    assert len(chunks) > 1, "a very long section should be split"
    for chunk in chunks:
        for line in chunk.text.splitlines():
            if line.strip():
                assert re.match(r"^(#|-)", line.strip()), f"chunk starts mid-bullet: {line!r}"


def test_heading_only_pieces_are_dropped():
    chunks = chunk_document(_resume())
    for chunk in chunks:
        lines = [line for line in chunk.text.splitlines() if line.strip()]
        assert len(lines) > 1, f"chunk contains only a heading: {chunk.text!r}"


def test_prose_chunks_respect_the_size_limit():
    text = "## Kubernetes\n\n" + ("Pods are the smallest deployable unit. " * 400)
    chunks = chunk_document(_prose(text))
    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk.text) <= PROSE_CHUNK_CHARS * 1.3  # splitter allows slight overshoot


def test_chunk_index_is_sequential_per_document():
    chunks = chunk_document(_resume())
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))


def test_metadata_contains_no_none_values():
    """Chroma rejects None in metadata."""
    for chunk in chunk_document(_resume()):
        meta = chunk.metadata()
        assert all(value is not None for value in meta.values())
        assert meta["source"] == "automotive_cyber.md"
        assert meta["profile"] == "automotive_cyber"


def test_guide_chunks_have_no_profile():
    doc = RawDocument(
        text="## Parse safety\n\n" + ("Single column layouts parse cleanly. " * 100),
        doc_type=DocType.GUIDE,
        profile=None,
        source="ats_guide.md",
        source_path="kb/guides/ats_guide.md",
    )
    for chunk in chunk_document(doc):
        assert chunk.profile is None
        assert "profile" not in chunk.metadata()


def test_chunk_documents_flattens_everything():
    chunks = chunk_documents([_resume(), _prose("## K8s\n\n" + "text " * 300)])
    assert len(chunks) == len(chunk_document(_resume())) + len(
        chunk_document(_prose("## K8s\n\n" + "text " * 300))
    )
