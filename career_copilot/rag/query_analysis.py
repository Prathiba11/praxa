"""Turn a natural-language question into intent plus retrieval filters.

This is "structured retrieval": similarity search alone has no concept of
"my DevOps CV" or "posted this week". An LLM extracts those constraints and
they become metadata predicates on the vector store.

Analysis is an enhancement, not a dependency - if the call fails, we degrade to
an unfiltered search rather than failing the user's question.
"""

from __future__ import annotations

import json
import re
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field
from pydantic import ValidationError as PydanticValidationError

from career_copilot.core.errors import CopilotError
from career_copilot.core.llm import chat
from career_copilot.core.logging import get_logger
from career_copilot.core.types import DocType, Profile

__all__ = ["Intent", "QueryAnalysis", "analyse_query"]

log = get_logger(__name__)

_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


class Intent(StrEnum):
    KB_QUESTION = "kb_question"  # "what experience do I have with X?"
    JOB_SEARCH = "job_search"  # "show me DevOps roles in Stuttgart"
    TAILORING = "tailoring"  # "tailor my CV for this posting"
    INTERVIEW = "interview"  # "ask me a STAR question about conflict"
    OUT_OF_DOMAIN = "out_of_domain"  # a subject the assistant does not cover at all


class QueryAnalysis(BaseModel):
    """What the question is asking for, and how to narrow the search."""

    intent: Intent = Intent.KB_QUESTION
    profiles: list[Profile] = Field(default_factory=list)
    doc_types: list[DocType] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    location: str | None = None
    posted_since_days: int | None = None
    confidence: float = 0.5

    def where(self) -> dict[str, Any] | None:
        """Chroma metadata filter, or None for an unfiltered search."""
        clauses: list[dict[str, Any]] = []
        if self.profiles:
            clauses.append({"profile": {"$in": [str(p) for p in self.profiles]}})
        if self.doc_types:
            clauses.append({"doc_type": {"$in": [str(d) for d in self.doc_types]}})

        if not clauses:
            return None
        if len(clauses) == 1:
            return clauses[0]
        return {"$and": clauses}


SYSTEM_PROMPT = """You analyse questions for a career assistant and return JSON only.

The assistant covers one person's job search across three professional profiles:
- automotive_cyber : automotive cybersecurity, ISO/SAE 21434, TARA, ECU security testing
- devops           : CI/CD, Kubernetes, Docker, observability, SRE
- ai_eng           : LLM applications, RAG, MLOps, AI engineering

Document types in the knowledge base:
- resume : the person's CVs, one per profile
- guide  : ATS/CV writing advice and interview (STAR) frameworks
- domain : reference notes on the technical domains above
- jd     : job postings

Return exactly this JSON shape, no prose, no code fences:
{
  "intent": "kb_question" | "job_search" | "tailoring" | "interview" | "out_of_domain",
  "profiles": [],          // only when the question clearly targets specific profiles
  "doc_types": [],         // only when the question clearly targets specific types
  "keywords": [],          // 2-6 key technical terms, in the question's own words
  "location": null,        // city or region if mentioned
  "posted_since_days": null,  // 1 for "today", 7 for "this week", 30 for "this month"
  "confidence": 0.0-1.0
}

Leave "profiles" and "doc_types" EMPTY unless the question is clearly specific.
An over-narrow filter hides the right answer; an empty filter merely widens the search.

Key signal: when the question uses "I", "my" or "do I have" about skills or
experience, it is asking about the person's CV - include "resume" in doc_types.

WHAT COUNTS AS IN SCOPE. A question about any of the three profiles above is in
scope even when it is phrased generally and never mentions the person. "What is
DevOps", "explain TARA", "why does RAG need reranking" are all "kb_question" -
they are answered from the "domain" notes.

"out_of_domain" is only for subjects the assistant does not cover at all:
weather, cooking, news, sport, general chit-chat, someone else's career, or
open-ended trivia with no connection to these three fields or to job seeking.

When you are torn between "kb_question" and "out_of_domain", choose
"kb_question" and lower your confidence. The two mistakes are not equal: a
question let through that finds nothing already has an honest answer of its own
("nothing in your material covers that"), whereas a question wrongly refused
gets no answer at all, and the refusal contradicts a scope the assistant claims.

Examples:

Q: "what Kubernetes experience do I have?"
{"intent":"kb_question","profiles":["devops"],"doc_types":["resume"],
 "keywords":["Kubernetes","container orchestration","experience"],
 "location":null,"posted_since_days":null,"confidence":0.85}

Q: "what is DevOps?"
{"intent":"kb_question","profiles":["devops"],"doc_types":["domain"],
 "keywords":["DevOps","CI/CD","SRE"],
 "location":null,"posted_since_days":null,"confidence":0.7}

Q: "how do I answer a question about a career gap?"
{"intent":"interview","profiles":[],"doc_types":["guide"],
 "keywords":["career gap","behavioural question"],
 "location":null,"posted_since_days":null,"confidence":0.8}

Q: "what does ISO 21434 say about attack feasibility?"
{"intent":"kb_question","profiles":["automotive_cyber"],"doc_types":["domain"],
 "keywords":["ISO 21434","attack feasibility","TARA"],
 "location":null,"posted_since_days":null,"confidence":0.9}

Q: "show me DevOps roles in Stuttgart posted this week"
{"intent":"job_search","profiles":["devops"],"doc_types":["jd"],
 "keywords":["DevOps","Stuttgart"],
 "location":"Stuttgart","posted_since_days":7,"confidence":0.95}

Q: "what is the weather tomorrow?"
{"intent":"out_of_domain","profiles":[],"doc_types":[],"keywords":[],
 "location":null,"posted_since_days":null,"confidence":0.95}

Q: "give me a recipe for lentil soup"
{"intent":"out_of_domain","profiles":[],"doc_types":[],"keywords":[],
 "location":null,"posted_since_days":null,"confidence":0.95}

Always include every field, including confidence.
"""


def _extract_json(text: str) -> dict[str, Any]:
    """Models sometimes wrap JSON in prose or code fences."""
    match = _JSON_BLOCK.search(text)
    if not match:
        raise ValueError(f"no JSON object found in response: {text[:120]!r}")
    parsed: dict[str, Any] = json.loads(match.group(0))
    return parsed


def analyse_query(question: str, *, session_id: str | None = None) -> QueryAnalysis:
    """Extract intent and filters. Never raises - falls back to unfiltered."""
    try:
        result = chat(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": question},
            ],
            session_id=session_id,
            operation="query_analysis",
            temperature=0.0,
            max_tokens=300,
        )

        analysis = QueryAnalysis.model_validate(_extract_json(result.content or ""))

    except (CopilotError, ValueError, PydanticValidationError) as exc:
        log.warning(
            "query analysis failed - searching unfiltered",
            extra={"reason": type(exc).__name__, "detail": str(exc)[:200]},
        )
        return QueryAnalysis(confidence=0.0)

    log.info(
        "query analysed",
        extra={
            "intent": str(analysis.intent),
            "profiles": [str(p) for p in analysis.profiles],
            "doc_types": [str(d) for d in analysis.doc_types],
            "confidence": analysis.confidence,
        },
    )
    return analysis
