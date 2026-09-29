"""Discover and load knowledge-base documents, inferring metadata from paths.

Layout drives metadata, deliberately - no manifest file to drift out of sync:

    kb/guides/<name>.md                  -> GUIDE,  no profile
    kb/domain/<profile>/<name>.md        -> DOMAIN, profile from folder
    data/kb/resumes/<profile>.md         -> RESUME, profile from filename
    kb/resumes_sample/<profile>.md       -> RESUME, profile from filename,
                                            used ONLY when the folder above is
                                            empty. See `discover`.

Real CVs are personal data and are gitignored, so a clone of this repository
arrives with `data/kb/resumes/` empty. Without the sample CVs the index would
have guides and domain notes but nothing to say about anybody, and half the
application would have nothing to work on. The samples exist so a reviewer can
run the whole thing; they step aside the moment real CVs are present.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from career_copilot.core.config import get_settings
from career_copilot.core.errors import IngestionError
from career_copilot.core.logging import get_logger
from career_copilot.core.types import DocType, Profile

__all__ = ["SAMPLE_RESUME_DIR", "RawDocument", "discover", "load_all", "load_document"]

log = get_logger(__name__)

TODO_MARKER = "[[TODO"

# Both spellings mean "this file is a CV". The sample folder is a sibling of the
# guides and domain notes so it travels with the repository; the real one lives
# under `data/` so `.gitignore` can keep it out.
SAMPLE_RESUME_DIR = "resumes_sample"
_RESUME_DIRS = ("resumes", SAMPLE_RESUME_DIR)


class RawDocument(BaseModel):
    text: str
    doc_type: DocType
    profile: Profile | None
    source: str  # file name, shown in citations
    source_path: str  # full path, for debugging


def _profile_or_none(value: str) -> Profile | None:
    try:
        return Profile(value)
    except ValueError:
        return None


def discover(kb_dir: Path | None = None, resume_dir: Path | None = None) -> list[Path]:
    """Every markdown file in the knowledge base, sorted for deterministic order.

    The sample CVs are a fallback, not an addition. If real CVs are present they
    win outright and the samples are dropped - indexing both would put a real
    career and an invented one under the same profile, and the assistant would
    cite whichever the retriever happened to rank, which is the one failure mode
    this application must not have.
    """
    settings = get_settings()
    kb = kb_dir or Path("kb")
    resumes = resume_dir or (settings.data_dir / "kb" / "resumes")

    # Top-level files are one-per-track: `devops.md` is *the* DevOps CV.
    # `general/` is a shelf instead - several CVs that share the General track,
    # because that track exists for careers the three specialised ones do not
    # cover and there is no single document that represents "everything else".
    real_resumes = sorted(resumes.glob("*.md")) + sorted((resumes / "general").glob("*.md"))
    kb_files = sorted(kb.rglob("*.md"))

    if real_resumes:
        kb_files = [path for path in kb_files if SAMPLE_RESUME_DIR not in path.parts]
        log.info("using real CVs", extra={"count": len(real_resumes), "dir": str(resumes)})
    else:
        samples = [path for path in kb_files if SAMPLE_RESUME_DIR in path.parts]
        log.warning(
            "no CVs in %s - falling back to the %s sample CVs, which describe fictional people",
            resumes,
            len(samples),
        )

    found = kb_files + real_resumes
    if not found:
        raise IngestionError(f"no markdown found under {kb} or {resumes}")
    return found


def load_document(path: Path) -> RawDocument:
    """Read one file and infer its metadata from where it sits.

    Raises:
        IngestionError: unreadable, empty, unrecognised location, or still
            containing an unresolved [[TODO placeholder.
    """
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise IngestionError(f"cannot read {path}: {exc}") from exc
    if not text:
        raise IngestionError(f"empty document: {path}")
    if TODO_MARKER in text:
        raise IngestionError(
            f"{path.name} still contains {TODO_MARKER} - fill it in before indexing"
        )

    parts = path.parts
    if any(directory in parts for directory in _RESUME_DIRS):
        doc_type = DocType.RESUME
        # Inside `general/` the filename is a label chosen by the user, so the
        # profile comes from the folder. Everywhere else the filename *is* the
        # profile, and a name that is not one is a mistake worth refusing: a CV
        # indexed under no profile would be retrievable by every track.
        if path.parent.name == str(Profile.GENERAL):
            profile = Profile.GENERAL
        else:
            named = _profile_or_none(path.stem)
            if named is None:
                raise IngestionError(f"resume filename must be a profile name: {path.name}")
            profile = named
    elif "guides" in parts:
        doc_type, profile = DocType.GUIDE, None
    elif "domain" in parts:
        doc_type = DocType.DOMAIN
        profile = _profile_or_none(path.parent.name)
        if profile is None:
            raise IngestionError(f"domain folder must be a profile name: {path.parent.name}")
    else:
        raise IngestionError(f"cannot infer document type from path: {path}")

    return RawDocument(
        text=text,
        doc_type=doc_type,
        profile=profile,
        source=path.name,
        source_path=str(path),
    )


def load_all(kb_dir: Path | None = None, resume_dir: Path | None = None) -> list[RawDocument]:
    docs = [load_document(p) for p in discover(kb_dir, resume_dir)]
    log.info("loaded knowledge base", extra={"documents": len(docs)})
    return docs
