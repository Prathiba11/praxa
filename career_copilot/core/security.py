"""Input validation and PII masking.

Masking policy is tiered, deliberately:

| context                        | masked? |
|--------------------------------|---------|
| chat input -> LLM              | yes     |
| resume text -> tailor_cv       | NO - the model cannot rewrite a CV it cannot
|                                | read. Explicit, logged, consented.          |
| logs / traces / stored history | always  |
| generated documents on disk    | no (local only, gitignored) |
| committed fixtures             | fully redacted |

Personal NAMES are not masked by the regex layer - regex cannot reliably detect
names. NER (presidio or spaCy de/en models) is planned for a later phase. Until
then, names in chat input reach the model. This is a documented, accepted risk.
"""

from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlparse

from pydantic import BaseModel

from career_copilot.core.errors import SecurityError, ValidationError

__all__ = [
    "MAX_INPUT_CHARS",
    "MaskResult",
    "mask_pii",
    "validate_url",
    "validate_user_input",
]

MAX_INPUT_CHARS = 8_000  # config overrides this later

_BLOCKED_HOSTS = frozenset({"localhost", "0.0.0.0", "::1"})

# Order matters. Specific patterns run before greedy ones:
#   linkedin before url  - otherwise \S+ swallows the profile and we lose the label
#   email    before url  - same reason
#   url      last        - greediest pattern in the list
PII_PATTERNS: list[tuple[str, str]] = [
    ("linkedin", r"(?:https?://)?(?:[\w]+\.)?linkedin\.com/in/[\w\-%]+"),
    ("email", r"[\w.\-+]+@[\w\-]+\.[\w.\-]+"),
    ("iban", r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b"),
    ("phone_de", r"(?:\+49|0049)\s?[\d\s\-/()]{6,}\d|\b0\d{2,4}[\s\-/]?\d{5,}\b"),
    ("phone_intl", r"\+\d{1,3}[\s\-]?\(?\d{1,4}\)?[\s\-]?[\d\s\-]{5,}\d"),
    (
        "street_de",
        r"\b[A-ZÄÖÜ][\wäöüß\-]*"
        r"(?:straße|strasse|str\.|weg|allee|platz|gasse|ring)"
        r"\s+\d+\s?[a-zA-Z]?\b",
    ),
    (
        "street_en",
        r"\b\d{1,5}\s+[A-Z][\w\-]+\s+"
        r"(?:Street|St\.|Road|Rd\.|Avenue|Ave\.|Lane|Ln\.)\b",
    ),
    ("plz_city", r"\b\d{5}\s+[A-ZÄÖÜ][\wäöüß\-]+\b"),
    ("dob", r"\b(?:0?[1-9]|[12]\d|3[01])[./-](?:0?[1-9]|1[012])[./-](?:19|20)\d{2}\b"),
    ("url", r"(?:https?://|www\.)\S+"),
]

# Compiled once at import, not on every call.
_COMPILED: list[tuple[str, re.Pattern[str]]] = [
    (name, re.compile(pattern)) for name, pattern in PII_PATTERNS
]


class MaskResult(BaseModel):
    """Masked text plus a count of what was found, by category.

    The counts let callers log *that* PII was present without logging *what*.
    """

    text: str
    found: dict[str, int]


def validate_user_input(text: str, *, max_chars: int = MAX_INPUT_CHARS) -> str:
    """Reject unusable input and return a cleaned string.

    Raises:
        ValidationError: input is empty, too long, or otherwise unusable.
    """
    if not text or not text.strip():
        raise ValidationError("empty or whitespace-only input")

    if len(text) > max_chars:
        raise ValidationError(f"input too long: {len(text)} chars, limit {max_chars}")

    # Drop control characters but keep newlines and tabs - users paste formatted text.
    cleaned = "".join(ch for ch in text if ch.isprintable() or ch in "\n\t")
    return cleaned.strip()


def validate_url(url: str) -> str:
    """Allow only public https URLs.

    Used by the paste-a-job-URL feature. Note this checks the *literal* hostname;
    a public domain that resolves to an internal address would still pass. Full
    SSRF protection requires resolving DNS at fetch time - a known limitation.

    Raises:
        SecurityError: scheme, host, or address is not permitted.
    """
    parsed = urlparse(url)

    if parsed.scheme != "https":
        raise SecurityError(f"unsupported URL scheme {parsed.scheme!r}")

    hostname = parsed.hostname
    if not hostname:
        raise SecurityError("URL has no hostname")

    if hostname.lower() in _BLOCKED_HOSTS:
        raise SecurityError(f"blocked host {hostname!r}")

    try:
        ip = ipaddress.ip_address(hostname)
    except ValueError:
        pass  # not an IP literal, so it is a domain name - allowed
    else:
        if ip.is_private or ip.is_loopback or ip.is_link_local:
            raise SecurityError(f"blocked private address {hostname!r}")

    return url


def mask_pii(text: str) -> MaskResult:
    """Replace detected PII with category tokens such as [EMAIL].

    Category tokens rather than asterisks, so the model still knows what kind of
    value was removed and the sentence stays readable.
    """
    found: dict[str, int] = {}
    for name, pattern in _COMPILED:
        text, count = pattern.subn(f"[{name.upper()}]", text)
        if count:
            found[name] = count
    return MaskResult(text=text, found=found)
