"""Helpers shared by the document and scoring tools.

Nothing here is exposed to the model. These are the boring bits - finding the
repository root, reading a resume off disk, turning a job id into text - kept in
one place so the tools themselves stay readable.

``parse_json_object`` now lives in ``core.jsonio``; the interview rubric needs it
too and importing it from here made a cycle. It is re-exported so the tools that
already import it from this module keep working.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from career_copilot.core.errors import ToolError
from career_copilot.core.jsonio import parse_json_object
from career_copilot.core.logging import get_logger
from career_copilot.core.moderation import moderate
from career_copilot.core.types import Profile
from career_copilot.storage import jobs as jobs_repo

__all__ = [
    "JobContext",
    "load_resume",
    "output_dir",
    "parse_json_object",
    "repo_root",
    "resolve_job",
    "save_output",
    "short_hash",
]

log = get_logger(__name__)

_RESUME_SUBPATH = Path("data") / "kb" / "resumes"
# Committed sample CVs, describing fictional people. Real CVs are personal data
# and gitignored, so this is what a fresh clone has to work with. Same fallback
# rule as `rag.loaders.discover`: real CVs win whenever they exist.
_SAMPLE_SUBPATH = Path("kb") / "resumes_sample"


def repo_root() -> Path:
    """Walk up from this file until the knowledge base is in sight.

    Deliberately not cwd-relative: the tools are called from Streamlit, from
    pytest and from scripts, and those three run from different directories.

    `data/kb/resumes/` holds a committed `.gitkeep` precisely so that this still
    resolves on a fresh clone, where every real CV in it has been gitignored
    away. The sample directory is accepted as well, so the lookup does not
    depend on an empty folder surviving a zip, an export or a copy.
    """
    for parent in Path(__file__).resolve().parents:
        if (parent / _RESUME_SUBPATH).is_dir() or (parent / _SAMPLE_SUBPATH).is_dir():
            return parent
    raise ToolError(f"could not locate {_RESUME_SUBPATH} above {Path(__file__).resolve()}")


def output_dir() -> Path:
    path = repo_root() / "data" / "output"
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_resume(profile: Profile) -> str:
    """Read a whole resume, not retrieved fragments.

    Tailoring needs the complete document: chunks would silently drop whichever
    role the retriever happened not to rank. Retrieval is for questions; this is
    a document operation.

    Falls back to the committed sample CV when there is no real one for this
    profile, so a clone of the repository can tailor and score straight away.
    The fallback is logged rather than silent - a tailored CV built from an
    invented career is worth knowing about.

    `Profile.GENERAL` is a shelf of several CVs rather than one file, and this
    takes the most recently updated of them. That choice is documented in the
    interface too, because a tool that silently picks one of your documents is
    worse than one that picks predictably and says which.
    """
    root = repo_root()

    if profile is Profile.GENERAL:
        # The General track is a shelf rather than a slot, so one file has to be
        # chosen. The rule is the most recently updated, and it is a rule rather
        # than a guess: nothing else can decide. The classifier never assigns a
        # posting to General, so there is no signal from the job either, and
        # asking the user on every call would make the tool unusable inside an
        # agent loop. Whichever was uploaded last is the one being worked on.
        shelf = sorted(
            (root / _RESUME_SUBPATH / str(Profile.GENERAL)).glob("*.md"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
        if shelf:
            chosen = shelf[0]
            if len(shelf) > 1:
                log.info(
                    "several General CVs on the shelf - using the most recent",
                    extra={"chosen": chosen.name, "available": len(shelf)},
                )
            text = chosen.read_text(encoding="utf-8").strip()
            if not text:
                raise ToolError(f"resume '{chosen.name}' is empty")
            return text

    path = root / _RESUME_SUBPATH / f"{profile}.md"

    if not path.is_file():
        sample = root / _SAMPLE_SUBPATH / f"{profile}.md"
        if not sample.is_file():
            raise ToolError(f"no resume on disk for profile '{profile}' (looked in {path})")
        log.warning(
            "no real CV for profile - using the sample, which describes a fictional person",
            extra={"profile": str(profile), "path": str(sample)},
        )
        path = sample

    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise ToolError(f"resume for profile '{profile}' is empty")
    return text


@dataclass(frozen=True)
class JobContext:
    """A job to work against, whether it came from the database or a paste."""

    job_id: str | None
    title: str
    company: str
    location: str | None
    text: str

    @property
    def label(self) -> str:
        where = f", {self.location}" if self.location else ""
        return f"{self.title} at {self.company}{where}" if self.company else self.title

    @property
    def slug(self) -> str:
        return self.job_id or short_hash(self.text)


def _screen(text: str, *, label: str) -> None:
    """Classify external text and record a hit. Never refuses, never raises."""
    result = moderate(text)
    if result.flagged:
        log.warning(
            "external text flagged by moderation - delimited and used anyway",
            extra={"what": label, "categories": list(result.hits)},
        )


def resolve_job(job_id: str | None, job_text: str | None) -> JobContext:
    """Accept either a stored job or pasted text, never both, never neither.

    Every posting that reaches a model goes through here, which is why the
    moderation call sits at this one point rather than at each of the four
    tools that use a posting. A job posting is text a stranger wrote, fetched
    automatically; the classifier is asked whether it carries an instruction
    phrased so the existing rules would not catch it.

    A flagged posting is **logged, not refused**. Refusing would mean a user
    cannot read a job they found themselves because a third-party classifier
    disliked it, and the delimiting that already treats this text as data is
    what actually stops it being obeyed. The log line is what makes a hit
    visible afterwards.
    """
    if job_id and job_text:
        raise ToolError("pass either job_id or job_text, not both")
    if job_id:
        job = jobs_repo.get_job(job_id)
        if job is None:
            raise ToolError(f"no job stored with id '{job_id}'")
        _screen(job.description, label=f"stored posting {job.id}")
        return JobContext(
            job_id=job.id,
            title=job.title,
            company=job.company,
            location=job.location,
            text=job.description,
        )
    if job_text and job_text.strip():
        _screen(job_text, label="pasted posting")
        return JobContext(
            job_id=None,
            title="(pasted job description)",
            company="",
            location=None,
            text=job_text.strip(),
        )
    raise ToolError("a job is required: pass job_id for a stored job, or job_text to paste one")


def short_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def save_output(filename: str, content: str) -> Path:
    path = output_dir() / filename
    path.write_text(content, encoding="utf-8")
    log.info("artifact written", extra={"path": str(path), "chars": len(content)})
    return path
