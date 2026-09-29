"""What a job source is, and the normalisation every source shares.

One interface, several sources. `JobSource.fetch` returns `JobPosting` objects
and nothing else, so adding a second board later is a new class rather than a
change to the storage layer, the tools or the UI.

**Why an API and not a scraper.** LinkedIn, Xing and Indeed all forbid automated
collection in their terms, and a project that quietly breaks them is not one to
put a name on. Arbeitnow publishes a free, unauthenticated job-board API and is
strong on the German market, which is the market that matters here. Anything it
does not carry can be pasted in by hand - see `paste.py`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Protocol, runtime_checkable

import httpx

from career_copilot.core.config import get_settings
from career_copilot.core.errors import CopilotError
from career_copilot.core.types import Profile

__all__ = [
    "JobPosting",
    "JobSource",
    "JobSourceError",
    "build_client",
    "classify_profile",
    "detect_language",
    "html_to_text",
]


def build_client(timeout: float, *, follow_redirects: bool = False) -> httpx.Client:
    """An HTTP client for a job source, honouring `CC_FORCE_IPV4`.

    The setting already existed for the model client, where the same problem was
    found and fixed. The job sources built their own bare `httpx.Client` and so
    never saw it, which cost a measured **63 seconds per source**: Arbeitnow and
    Remotive both sit behind Cloudflare and publish IPv6 addresses, Python tries
    the resolved addresses in order, and on a machine with no IPv6 route it
    waits out a TCP timeout on each one before reaching IPv4. The Bundesagentur
    publishes no IPv6 record, which is the only reason it answered in 0.3s and
    looked like the fast source.

    `scripts/diagnose_latency.py --connect` is what tells a given machine which
    case it is in.
    """
    settings = get_settings()
    return httpx.Client(
        timeout=timeout,
        follow_redirects=follow_redirects,
        transport=httpx.HTTPTransport(
            local_address="0.0.0.0" if settings.force_ipv4 else None,
        ),
    )


class JobSourceError(CopilotError):
    user_message = "Job listings could not be fetched right now."


@dataclass(frozen=True)
class JobPosting:
    """A posting as a source hands it over, before it becomes a database row.

    Deliberately separate from the `Job` model: sources change, the schema
    should not have to. Everything here is already normalised - HTML stripped,
    language detected, profile guessed - so the storage layer receives plain
    values and makes no decisions.
    """

    source: str
    title: str
    company: str
    description: str
    location: str | None = None
    url: str | None = None
    posted_at: datetime | None = None
    language: str | None = None
    profile: Profile | None = None
    tags: tuple[str, ...] = field(default_factory=tuple)


@runtime_checkable
class JobSource(Protocol):
    """Anything that can produce postings.

    A Protocol rather than a base class: a source has no shared behaviour worth
    inheriting, only a shared shape, and this keeps test doubles trivial.
    """

    name: str

    def fetch(self, *, limit: int = 50) -> list[JobPosting]:
        """Return up to `limit` postings. Raises JobSourceError on failure."""
        ...


# ---------------------------------------------------------------- HTML

_BLOCK_TAGS = {"p", "br", "li", "div", "tr", "h1", "h2", "h3", "h4", "h5", "h6"}
_DROP_TAGS = {"script", "style"}


class _TextExtractor(HTMLParser):
    """Just enough HTML handling, with no new dependency.

    Job descriptions arrive as markup. BeautifulSoup would be the obvious tool,
    but this needs to preserve paragraph breaks and drop scripts, and that is
    forty lines of the standard library rather than another package in the
    container image.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _DROP_TAGS:
            self._skip += 1
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _DROP_TAGS and self._skip:
            self._skip -= 1
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)


_BLANK_LINES = re.compile(r"\n\s*\n\s*\n+")
_TRAILING_SPACE = re.compile(r"[ \t]+\n")


def html_to_text(markup: str) -> str:
    """Readable plain text from a job description."""
    if not markup:
        return ""
    parser = _TextExtractor()
    parser.feed(markup)
    parser.close()
    text = "".join(parser.parts)
    text = _TRAILING_SPACE.sub("\n", text)
    return _BLANK_LINES.sub("\n\n", text).strip()


# ---------------------------------------------------------------- language

# Function words, not content words: "Entwicklung" appears in English postings
# for German companies, "und" does not.
_GERMAN_MARKERS = re.compile(
    r"\b(und|oder|mit|für|nicht|eine|einen|einer|dein|deine|ihre|wir|sie|"
    r"sind|werden|haben|bei|von|zum|zur|das|des|dem|den|auf|als|auch)\b",
    re.IGNORECASE,
)
_WORD = re.compile(r"\w+", re.UNICODE)
_GERMAN_THRESHOLD = 0.04


def detect_language(text: str) -> str:
    """'de' or 'en', by German function-word density.

    A heuristic, not a language model. It only has to separate two languages on
    text hundreds of words long, and it costs nothing - which matters because
    every posting goes through it.
    """
    words = _WORD.findall(text)
    if len(words) < 20:
        return "en"
    density = len(_GERMAN_MARKERS.findall(text)) / len(words)
    return "de" if density >= _GERMAN_THRESHOLD else "en"


# ---------------------------------------------------------------- profile

# Weighted so that a single passing mention does not decide a profile. The
# vocabularies are deliberately narrow: a posting that says "cloud" is not
# evidence of anything.
_PROFILE_TERMS: dict[Profile, tuple[str, ...]] = {
    Profile.AUTOMOTIVE_CYBER: (
        "automotive cybersecurity",
        "vehicle security",
        "iso 21434",
        "iso/sae 21434",
        "unece",
        "r155",
        "r156",
        "tara",
        "csms",
        "sums",
        "automotive",
        "ecu",
        "steuergerät",
        "can bus",
        "autosar",
        "aspice",
        "penetration test",
        "threat analysis",
        "bedrohungsanalyse",
        "vehicle",
        "fahrzeug",
        "homologation",
    ),
    Profile.DEVOPS: (
        "devops",
        "dev ops",
        "sysadmin",
        "kubernetes",
        "k8s",
        "terraform",
        "ansible",
        "docker",
        "helm",
        "gitops",
        "argocd",
        "ci/cd",
        "gitlab ci",
        "github actions",
        "jenkins",
        "prometheus",
        "grafana",
        "site reliability",
        "sre",
        "platform engineer",
        "infrastructure as code",
        "observability",
    ),
    Profile.AI_ENG: (
        "ai engineer",
        "generative ai",
        "genai",
        "machine learning",
        "deep learning",
        "llm",
        "large language model",
        "rag",
        "retrieval augmented",
        "mlops",
        "pytorch",
        "tensorflow",
        "langchain",
        "embedding",
        "vector database",
        "prompt engineering",
        "fine-tuning",
        "nlp",
        "data scientist",
    ),
}

_TITLE_WEIGHT = 3
_MIN_SCORE_WITH_TITLE_EVIDENCE = 2
_MIN_BODY_ONLY_SCORE = 6
_MIN_MARGIN = 3


def classify_profile(title: str, description: str, tags: tuple[str, ...] = ()) -> Profile | None:
    """Guess which CV a posting belongs to, or admit it does not know.

    Keyword scoring rather than an LLM call: this runs on every posting of every
    sync, the vocabulary is small and stable, and a wrong guess here is cheap to
    override. Returning None is a real outcome - a mislabelled job is worse than
    an unlabelled one, because the profile becomes a retrieval filter and hides
    the job from the search that would have found it.

    Three rules, each earned from a real misclassification:

    - **The title usually says so.** A DevOps role says DevOps, Kubernetes or
      SRE in its title. A body-only match has to be much stronger to count.
    - **A margin is required.** A first live run labelled a *Senior Graphic
      Designer* as AI engineering, because the agency's boilerplate listed every
      technology it had ever touched. Boilerplate scores every profile roughly
      equally, so requiring the winner to lead by a clear margin rejects it.
    - **Ties are unresolved, not broken.** A posting that genuinely spans two
      profiles gets neither.
    """
    haystack = f"{description}\n{' '.join(tags)}".lower()
    title_text = title.lower()

    title_hits: dict[Profile, int] = {}
    body_hits: dict[Profile, int] = {}
    totals: dict[Profile, int] = {}

    for profile, terms in _PROFILE_TERMS.items():
        title_hits[profile] = sum(1 for term in terms if term in title_text)
        body_hits[profile] = sum(1 for term in terms if term in haystack)
        totals[profile] = body_hits[profile] + _TITLE_WEIGHT * title_hits[profile]

    best = max(totals, key=lambda p: totals[p])
    runner_up = sorted(totals.values(), reverse=True)[1]

    if totals[best] - runner_up < _MIN_MARGIN:
        return None

    if title_hits[best]:
        return best if totals[best] >= _MIN_SCORE_WITH_TITLE_EVIDENCE else None
    return best if body_hits[best] >= _MIN_BODY_ONLY_SCORE else None


def utc(value: datetime | None) -> datetime | None:
    """Normalise to aware UTC, since sources disagree about timezones."""
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
