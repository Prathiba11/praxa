"""Deciding what, out of a finished turn, is worth remembering.

**It runs after the answer, never before it.** The user has their answer and the
stream has closed by the time this starts; extraction costs them nothing in
latency, and if it fails they never find out. That ordering is the whole design
- a memory feature that makes every answer slower is a memory feature people
turn off.

**It only keeps what the user said about themselves.** Not what the assistant
replied, not what a document contained, not an inference about what they
probably want. "I only want remote roles" is a fact about the user; "your CV
mentions Kubernetes" is a fact about a file, and the file is already indexed.
The prompt below says so in as many words, because the failure mode is a store
slowly filling with the assistant's own opinions of the user.

**It never blocks anything.** Every failure path returns no facts and logs. The
turn already succeeded; nothing that happens here may change that.
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, Field
from pydantic import ValidationError as PydanticValidationError

from career_copilot.core.config import get_settings
from career_copilot.core.errors import CopilotError
from career_copilot.core.llm import chat
from career_copilot.core.logging import get_logger
from career_copilot.core.security import mask_pii
from career_copilot.core.tracing import traced
from career_copilot.storage import memory as store
from career_copilot.storage.db import init_db

__all__ = ["CATEGORIES", "ExtractedFact", "extract_facts", "remember_turn"]

log = get_logger(__name__)

_JSON_ARRAY = re.compile(r"\[.*\]", re.DOTALL)

#: The categories a fact can have. A closed set, because the recall block groups
#: by it and an open one would let the model invent a heading per turn.
CATEGORIES = ("role", "location", "language", "must_have", "deal_breaker", "application", "other")

#: How much of the turn the extractor reads. It is looking for a sentence the
#: user wrote about themselves, which is near the start of what they typed; the
#: answer is included only so that "yes, that one" can be resolved.
_MAX_QUESTION = 1200
_MAX_ANSWER = 800

#: Facts one turn may contribute. A turn that appears to produce eight new
#: standing preferences has misunderstood the question, and taking two is a
#: cheaper correction than letting the store fill.
_MAX_PER_TURN = 3

_PROMPT = """You extract durable facts about ONE job-seeker from a conversation turn.

Return a JSON array. Each element is:
{"category": "<one of: role, location, language, must_have, deal_breaker, application, other>",
 "text": "<the fact, in under 15 words, written in the third person>"}

Return [] when the turn contains none. That is the common case, and an empty
array is a correct answer - do not invent a fact to fill it.

A fact qualifies only if ALL of these hold:
- The USER stated it about themselves. Not the assistant's reply, not the
  content of a retrieved document, not something you inferred.
- It is still true next week. "I am looking for DevOps roles in Stuttgart" is
  durable; "what does OOMKilled mean" is not.
- It would change how a future answer is written.

Never extract:
- Anything the assistant said, including its summaries of the user.
- Facts about a company, a posting, or a standard. Those are indexed already.
- Skills or experience. Those are in the CVs; repeating them here is noise.
- Contact details, addresses, or anything identifying beyond a city.

Examples:
- "I only want remote or Stuttgart-based roles" -> location, "only wants remote or Stuttgart roles"
- "I won't do on-call" -> deal_breaker, "will not take roles with on-call"
- "I applied to the Bosch one yesterday" -> application, "applied to the Bosch platform role"
- "what is TARA?" -> [] (a question, not a fact about them)
"""


class ExtractedFact(BaseModel):
    category: str = Field(default="other")
    text: str = Field(min_length=3, max_length=300)


def _extract_json(text: str) -> list[dict[str, Any]]:
    match = _JSON_ARRAY.search(text)
    if not match:
        raise ValueError(f"no JSON array found in response: {text[:120]!r}")
    parsed: list[dict[str, Any]] = json.loads(match.group(0))
    return parsed


@traced("extract memory", run_type="chain")
def extract_facts(
    question: str, answer: str, *, session_id: str | None = None
) -> list[ExtractedFact]:
    """Read one finished turn and return what is worth keeping. Never raises.

    Uses the grader's model, not the chat model: this is a small extraction
    job that runs on every turn, and paying writing rates for it would double
    the cost of the feature for no gain in quality.
    """
    settings = get_settings()
    if not settings.memory_enabled:
        return []

    try:
        result = chat(
            [
                {"role": "system", "content": _PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"USER SAID:\n{question[:_MAX_QUESTION]}\n\n"
                        f"ASSISTANT REPLIED (context only, never a source of facts):\n"
                        f"{answer[:_MAX_ANSWER]}"
                    ),
                },
            ],
            session_id=session_id,
            operation="extract_memory",
            model=settings.grader_model,
            temperature=0.0,
            max_tokens=300,
        )
        raw = _extract_json(result.content or "")
    except (CopilotError, ValueError, PydanticValidationError) as exc:
        log.warning(
            "memory extraction failed - nothing remembered from this turn",
            extra={"reason": type(exc).__name__, "detail": str(exc)[:200]},
        )
        return []

    facts: list[ExtractedFact] = []
    for item in raw[:_MAX_PER_TURN]:
        try:
            fact = ExtractedFact.model_validate(item)
        except PydanticValidationError:
            continue
        if fact.category not in CATEGORIES:
            fact.category = "other"
        facts.append(fact)
    return facts


def remember_turn(question: str, answer: str, *, session_id: str | None = None) -> int:
    """Extract from one turn and store what came back. Returns how many landed.

    The text is masked before it is stored. The extractor is told not to keep
    identifying details, but a prompt is a request and the store is a file on
    disk that outlives the conversation - so the rule is enforced here too,
    with the same masking the logs use.
    """
    facts = extract_facts(question, answer, session_id=session_id)
    if not facts:
        return 0

    init_db()
    stored = 0
    masked_categories: dict[str, int] = {}
    for fact in facts:
        masked = mask_pii(fact.text)
        for kind, count in masked.found.items():
            masked_categories[kind] = masked_categories.get(kind, 0) + count
        if store.remember(masked.text, category=fact.category) is not None:
            stored += 1

    log.info(
        "turn remembered",
        # What kind of PII was masked, never the value - the same rule the
        # logging filter follows, for the same reason.
        extra={"extracted": len(facts), "stored": stored, "masked": masked_categories},
    )
    return stored
