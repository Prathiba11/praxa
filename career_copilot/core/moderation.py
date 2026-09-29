"""Mistral Moderation, as a second check rather than the only one.

Asked for in an earlier code review: the existing defences are input validation,
PII regexes, trusted/untrusted prompt separation, a server-enforced tool
allowlist and a live red-team suite. All of those are *rules*, and a rule
catches what it was written to catch. A classifier catches the semantic version
- an instruction phrased so no regex matches it - and Mistral Moderation carries
dedicated `jailbreak` and `pii` categories for exactly that.

**It is an additional layer, never a replacement.** The review was explicit and
it is right: the trusted-instruction and untrusted-data separation stays,
because a moderation call that is down, slow or wrong must not become the only
thing standing between a job posting and a tool call. Everything that stopped an
injection yesterday still stops it today.

**Where it runs.** Before a tool-capable agent turn, and over external text
before that text reaches model context. Chat mode has one read-only tool and is
not gated: the cost of a call on every question is not repaid by moderating a
turn that cannot write anything.

**It fails open, loudly.** If the key is absent the check is *skipped* and says
so; if the call fails the turn continues and a warning is logged. That is a
deliberate choice and the uncomfortable half of it is stated here rather than
buried: a moderation layer that fails open is not a guarantee. It is a second
net under the ones that do not depend on a third party being reachable. The
alternative - refusing every turn when Mistral is unreachable - trades a rare
missed classification for a common outage, and for a single-user career
assistant that is the worse trade. `describe()` exists so the interface can say
which state it is in, because "is moderation on?" should be answerable by
looking at the screen.

**The key is read from the environment, not from `core.config`.** Same reasoning
as `audio/stt.py`: `MISTRAL_API_KEY` is an optional third-party credential that
the rest of the application has no opinion about, and putting it in `Settings`
would imply the app needs one.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

import httpx

from career_copilot.core.errors import SecurityError
from career_copilot.core.logging import get_logger

__all__ = [
    "CATEGORIES",
    "GATED_CATEGORIES",
    "ModerationResult",
    "describe",
    "is_configured",
    "moderate",
]

log = get_logger(__name__)

_API_URL = "https://api.mistral.ai/v1/moderations"
_CHAT_API_URL = "https://api.mistral.ai/v1/chat/moderations"
_MODEL = "mistral-moderation-2603"
_TIMEOUT = 8.0

#: Every category the classifier returns, as of moderation-2603.
CATEGORIES = (
    "sexual",
    "hate_and_discrimination",
    "violence_and_threats",
    "dangerous_and_criminal_content",
    "selfharm",
    "health",
    "financial",
    "law",
    "pii",
    "jailbreak",
)

#: The two this application acts on.
#:
#: A career assistant reads job postings and CVs. `health`, `financial` and
#: `law` fire constantly on legitimate material - a posting for a medical device
#: company, a CV mentioning salary, a role in compliance - and blocking those
#: would make the product unusable while teaching the user to ignore the
#: warning. `jailbreak` and `pii` are the two the review named, and they are the
#: two that mean something here: an instruction hidden in retrieved text, and
#: personal data about somebody other than the user.
GATED_CATEGORIES = ("jailbreak", "pii")

#: Above this, a gated category counts as a hit. Mistral returns a score per
#: category rather than a verdict, so the threshold is ours to set and ours to
#: justify: 0.7 is deliberately high, because a false positive here refuses a
#: legitimate posting and the cheaper failure is to let the other defences work.
THRESHOLD = 0.7


@dataclass(frozen=True)
class ModerationResult:
    """One classification, and whether the check actually ran.

    `source` is not decoration. `skipped` and `clean` must never look alike: a
    turn nobody moderated is not a turn that passed moderation, and the same
    distinction the document reviewer draws between `unavailable` and `ok`.
    """

    flagged: bool = False
    #: Category -> score, for the gated categories only.
    scores: dict[str, float] = field(default_factory=dict)
    #: "checked", "skipped" (no key), or "unavailable" (the call failed).
    source: str = "skipped"

    @property
    def ran(self) -> bool:
        return self.source == "checked"

    @property
    def hits(self) -> tuple[str, ...]:
        return tuple(name for name, score in self.scores.items() if score >= THRESHOLD)


def _api_key() -> str | None:
    key = os.environ.get("MISTRAL_API_KEY", "").strip()
    return key or None


def is_configured() -> bool:
    return _api_key() is not None


def describe() -> str:
    """What the interface should say about this control."""
    if not is_configured():
        return "not configured - set MISTRAL_API_KEY to turn it on"
    return f"{_MODEL}, gating {' and '.join(GATED_CATEGORIES)} above {THRESHOLD}"


def _scores_in(payload: Any) -> dict[str, float]:
    """Pull per-category scores out without pinning one response shape.

    The published example shows the SDK call rather than the wire format, and a
    shape guessed from a client library is a shape that breaks quietly. So this
    walks for a mapping of category names to numbers, which every documented
    variant contains somewhere, instead of indexing a path that may not exist.
    """
    found: dict[str, float] = {}

    def walk(node: Any) -> None:
        if isinstance(node, list):
            for item in node:
                walk(item)
            return
        if not isinstance(node, dict):
            return
        for key, value in node.items():
            if key in CATEGORIES and isinstance(value, int | float):
                # Keep the strongest reading if a category appears twice.
                found[key] = max(float(value), found.get(key, 0.0))
            else:
                walk(value)

    walk(payload)
    return found


def moderate(
    text: str,
    *,
    session_id: str | None = None,
    client: httpx.Client | None = None,
) -> ModerationResult:
    """Classify one piece of text. Never raises; the caller decides what to do.

    Raising here would make an unreachable third party into an outage, which is
    the trade this module's docstring argues against.

    `client` is injected by tests, the same way every job source takes one.
    The alternative - patching `httpx.Client` on this module - patches it
    globally, because `moderation.httpx` is the httpx module itself.
    """
    key = _api_key()
    if key is None or not text.strip():
        return ModerationResult(source="skipped")

    owned = client is None
    http = client or httpx.Client(timeout=_TIMEOUT)
    try:
        response = http.post(
            _API_URL,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"model": _MODEL, "input": [text[:8000]]},
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        # Loudly: a control that failed silently is worse than no control,
        # because the log is the only place anyone would find out.
        log.warning(
            "moderation unavailable - the turn continues on the other defences",
            extra={"error": f"{type(exc).__name__}: {exc}", "session_id": session_id},
        )
        return ModerationResult(source="unavailable")
    finally:
        if owned:
            http.close()

    all_scores = _scores_in(payload)
    gated = {name: all_scores.get(name, 0.0) for name in GATED_CATEGORIES}
    result = ModerationResult(
        flagged=any(score >= THRESHOLD for score in gated.values()),
        scores=gated,
        source="checked",
    )
    if result.flagged:
        log.warning(
            "moderation flagged content",
            extra={"categories": list(result.hits), "session_id": session_id},
        )
    return result


def enforce(
    text: str,
    *,
    what: str,
    session_id: str | None = None,
    client: httpx.Client | None = None,
) -> ModerationResult:
    """Moderate, and raise `SecurityError` on a hit.

    Used where a refusal is the right answer - a user's own message before a
    tool-capable turn. External text uses `moderate` instead and is *degraded*
    rather than refused, because a posting that trips the classifier is still a
    posting the user may want to read.
    """
    result = moderate(text, session_id=session_id, client=client)
    if result.flagged:
        raise SecurityError(f"{what} was flagged for {', '.join(result.hits)}")
    return result
