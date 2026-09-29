"""Postings that arrive by hand: a pasted URL, or pasted text.

The API covers a slice of the market. Everything else - the role a recruiter
emailed, the posting on a company's own careers page - gets pasted in here, and
from that point on is treated identically to a fetched job.

**The blocklist is a decision, not an oversight.** LinkedIn, Xing, Indeed and
StepStone all prohibit automated retrieval in their terms. Fetching them here
would work and would be wrong, so the URL path refuses them by name and says
so. Their content can still be used - copy the text and paste it - which keeps
the person in the loop where the terms require a person.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

import httpx

from career_copilot.core.errors import ValidationError
from career_copilot.core.logging import get_logger
from career_copilot.core.security import validate_url
from career_copilot.jobs.base import (
    JobPosting,
    JobSourceError,
    build_client,
    classify_profile,
    detect_language,
    html_to_text,
)

__all__ = ["BLOCKED_DOMAINS", "from_text", "from_url", "title_and_company_from_text"]

log = get_logger(__name__)

SOURCE_NAME = "pasted"
_TIMEOUT = 20.0
_MAX_BYTES = 2_000_000
_MIN_DESCRIPTION_CHARS = 120

# Sites whose terms of service forbid automated collection.
BLOCKED_DOMAINS = frozenset(
    {
        "linkedin.com",
        "xing.com",
        "indeed.com",
        "de.indeed.com",
        "stepstone.de",
        "monster.de",
        "glassdoor.com",
        "glassdoor.de",
    }
)

_TITLE_TAG = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
# Escapes rather than literals: en dash and em dash are exactly the characters
# a linter flags as ambiguous, and job page titles use all three.
_SEPARATORS = re.compile("\\s+[-\u2013\u2014|]\\s+")


def _domain_is_blocked(url: str) -> str | None:
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    for blocked in BLOCKED_DOMAINS:
        if host == blocked or host.endswith(f".{blocked}"):
            return blocked
    return None


def from_url(url: str, *, client: httpx.Client | None = None) -> JobPosting:
    """Fetch a posting from a company careers page or a permitted board.

    Raises:
        ValidationError: the URL is malformed, or the site forbids automation.
        JobSourceError: the page could not be fetched or held no usable text.
    """
    clean = validate_url(url)

    blocked = _domain_is_blocked(clean)
    if blocked:
        raise ValidationError(
            f"{blocked} forbids automated retrieval in its terms of service. "
            f"Open the posting, copy the text, and paste it in instead."
        )

    owned_client = client is None
    http = client or build_client(_TIMEOUT, follow_redirects=True)
    try:
        response = http.get(clean, headers={"User-Agent": "career-copilot/0.1"})
        response.raise_for_status()
        markup = response.text[:_MAX_BYTES]
    except httpx.HTTPError as exc:
        raise JobSourceError(f"could not fetch {clean}: {type(exc).__name__}: {exc}") from exc
    finally:
        if owned_client:
            http.close()

    title, company = _title_and_company(markup)
    body = html_to_text(markup)
    if len(body) < _MIN_DESCRIPTION_CHARS:
        raise JobSourceError(
            f"{clean} produced almost no text - the page is probably rendered by "
            f"JavaScript. Copy the posting and paste it instead."
        )

    log.info("posting fetched from url", extra={"url": clean, "chars": len(body)})
    return _build(title=title, company=company, description=body, url=clean)


def from_text(
    text: str,
    *,
    title: str | None = None,
    company: str | None = None,
    location: str | None = None,
    url: str | None = None,
) -> JobPosting:
    """Build a posting from text the user pasted.

    Title and company are optional because a pasted block often lacks them.
    Placeholders are used rather than guesses: an invented company name would
    flow into the fingerprint and split one job into two.
    """
    body = text.strip()
    if len(body) < _MIN_DESCRIPTION_CHARS:
        raise ValidationError(
            f"that is only {len(body)} characters - paste the whole posting so "
            f"fit scoring has something to work with"
        )
    return _build(
        title=(title or "").strip() or "Untitled role",
        company=(company or "").strip() or "Unknown company",
        description=body,
        location=location,
        url=url,
    )


def _build(
    *,
    title: str,
    company: str,
    description: str,
    location: str | None = None,
    url: str | None = None,
) -> JobPosting:
    return JobPosting(
        source=SOURCE_NAME,
        title=title,
        company=company,
        description=description,
        location=location,
        url=url,
        language=detect_language(f"{title}\n{description}"),
        profile=classify_profile(title, description),
    )


def _title_and_company(markup: str) -> tuple[str, str]:
    """Split a `<title>` like "Platform Engineer - Bosch" into its two halves.

    Best effort by design. When the split is not obvious the company becomes a
    placeholder the user can correct, because a wrong company name changes the
    deduplication fingerprint and would store the same job twice.
    """
    match = _TITLE_TAG.search(markup)
    if not match:
        return "Untitled role", "Unknown company"

    raw = " ".join(match.group(1).split())
    parts = [part.strip() for part in _SEPARATORS.split(raw) if part.strip()]
    if len(parts) >= 2:
        return parts[0], parts[-1]
    return raw or "Untitled role", "Unknown company"


# ------------------------------------------------------- reading a paste

# A posting pasted out of a browser almost always opens with the role on one
# line and the employer on the next, or "Role at Employer" / "Role - Employer"
# on one. These read that shape and give up quickly rather than guessing hard:
# a wrong company changes the fingerprint and stores one job as two.
_AT_SPLIT = re.compile(r"\s+(?:at|bei|@)\s+", re.IGNORECASE)
_NOISE = re.compile(r"^(apply|jetzt bewerben|bewerben|save|share|zurück|back)\b", re.IGNORECASE)
_MAX_HEADING = 120


def _meaningful_lines(text: str, limit: int = 6) -> list[str]:
    out: list[str] = []
    for raw in text.splitlines():
        line = " ".join(raw.split())
        if not line or _NOISE.match(line) or len(line) > _MAX_HEADING:
            continue
        out.append(line)
        if len(out) == limit:
            break
    return out


def title_and_company_from_text(text: str) -> tuple[str | None, str | None]:
    """Best-effort role and employer from pasted text. None where unsure.

    Returning None is a real answer. The caller substitutes a placeholder, and
    a placeholder the user can see and correct beats a confident wrong guess
    that silently splits one job into two rows.
    """
    lines = _meaningful_lines(text)
    if not lines:
        return None, None

    first = lines[0]

    # "DevOps Engineer at Bosch" / "DevOps Engineer bei Bosch"
    parts = _AT_SPLIT.split(first, maxsplit=1)
    if len(parts) == 2 and all(part.strip() for part in parts):
        return parts[0].strip(), parts[1].strip()

    # "DevOps Engineer - Bosch GmbH", on one line
    halves = [half.strip() for half in _SEPARATORS.split(first, maxsplit=1) if half.strip()]
    if len(halves) == 2:
        return halves[0], halves[1]

    # Role on one line, employer on the next.
    if len(lines) >= 2:
        return first, lines[1]
    return first, None
