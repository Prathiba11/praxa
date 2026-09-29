"""Generate better search queries than the user's phrasing.

The user's wording is one sample from many possible phrasings, and the corpus
may use none of them. Three strategies:

- multi-query : paraphrases, including a cross-language variant. This matters
  most here: an English question about "threat modelling" must reach a German
  posting about "Bedrohungsanalyse und Risikobewertung".
- step-back   : a broader question, so conceptual asks retrieve context rather
  than incidental specifics.
- HyDE        : embed a hypothetical *answer* instead of the question. A
  question and its answer look different to an embedding model; a fake answer
  and the real answer look similar. Used only for vague queries.

Like query analysis, this degrades: a failure returns the original question.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field
from pydantic import ValidationError as PydanticValidationError

from career_copilot.core.errors import CopilotError
from career_copilot.core.llm import chat
from career_copilot.core.logging import get_logger

if TYPE_CHECKING:
    from career_copilot.rag.query_analysis import QueryAnalysis

__all__ = ["QueryPlan", "expand_query"]

log = get_logger(__name__)

_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)

VAGUE_QUERY_WORDS = 6  # shorter questions benefit most from HyDE


class QueryPlan(BaseModel):
    """Every phrasing that will be searched, plus how each was produced."""

    original: str
    paraphrases: list[str] = Field(default_factory=list)
    step_back: str | None = None
    hyde: str | None = None
    keywords: list[str] = Field(default_factory=list)

    def search_queries(self) -> list[str]:
        """Deduplicated, order preserved - the original always ranks first."""
        candidates = [self.original, *self.paraphrases]
        if self.step_back:
            candidates.append(self.step_back)
        if self.hyde:
            candidates.append(self.hyde)

        seen: set[str] = set()
        unique: list[str] = []
        for query in candidates:
            key = query.strip().lower()
            if key and key not in seen:
                seen.add(key)
                unique.append(query.strip())
        return unique

    def labelled(self) -> list[tuple[str, str]]:
        """(strategy, query) pairs - used by the RAG-trace UI expander."""
        pairs = [("original", self.original)]
        pairs += [("paraphrase", p) for p in self.paraphrases]
        if self.step_back:
            pairs.append(("step-back", self.step_back))
        if self.hyde:
            pairs.append(("hyde", self.hyde))
        return pairs


TRANSLATE_PROMPT = """You rewrite search queries for a bilingual knowledge base
covering automotive cybersecurity, DevOps, AI engineering, CV writing and
interview preparation. Documents are in English; job postings are often German.

Given a question, produce:
- "paraphrases": 3 alternative phrasings that would match differently worded
  passages. Vary the vocabulary, not just the word order. Make at least ONE a
  German technical phrasing if the question is English (or English if German),
  using the terms a practitioner would actually write.
- "step_back": one broader, more conceptual version of the question.

Return JSON only, no prose, no code fences:
{"paraphrases": ["...", "...", "..."], "step_back": "..."}
"""

HYDE_PROMPT = """Write a short, plausible passage (2-3 sentences) that would
answer the question, as if extracted from a professional reference document or
a CV. Do not hedge, do not say you are unsure, do not mention the question.
Output the passage only - it is used as a search key, not shown to anyone.
"""


def _extract_json(text: str) -> dict[str, object]:
    match = _JSON_BLOCK.search(text)
    if not match:
        raise ValueError(f"no JSON object in response: {text[:120]!r}")
    parsed: dict[str, object] = json.loads(match.group(0))
    return parsed


def _generate_hyde(question: str, session_id: str | None) -> str | None:
    try:
        result = chat(
            [
                {"role": "system", "content": HYDE_PROMPT},
                {"role": "user", "content": question},
            ],
            session_id=session_id,
            operation="hyde",
            temperature=0.3,
            max_tokens=160,
        )
    except CopilotError as exc:
        log.warning("hyde generation failed", extra={"reason": type(exc).__name__})
        return None

    passage = (result.content or "").strip()
    return passage if len(passage) > 40 else None


def expand_query(
    question: str,
    *,
    analysis: QueryAnalysis | None = None,
    use_hyde: bool | None = None,
    session_id: str | None = None,
) -> QueryPlan:
    """Build the set of queries to search with. Never raises."""
    plan = QueryPlan(
        original=question,
        keywords=list(analysis.keywords) if analysis else [],
    )

    try:
        result = chat(
            [
                {"role": "system", "content": TRANSLATE_PROMPT},
                {"role": "user", "content": question},
            ],
            session_id=session_id,
            operation="query_translation",
            temperature=0.3,
            max_tokens=300,
        )

        payload = _extract_json(result.content or "")

        # The model can return anything here; validate the shape rather than
        # trusting it. A malformed field degrades to "no paraphrases".
        raw_paraphrases = payload.get("paraphrases")
        if isinstance(raw_paraphrases, list):
            plan.paraphrases = [str(p) for p in raw_paraphrases if str(p).strip()][:4]

        raw_step_back = payload.get("step_back")
        if isinstance(raw_step_back, str) and raw_step_back.strip():
            plan.step_back = raw_step_back.strip()

    except (CopilotError, ValueError, PydanticValidationError) as exc:
        log.warning(
            "query translation failed - searching with the original only",
            extra={"reason": type(exc).__name__, "detail": str(exc)[:200]},
        )
        return plan

    # HyDE costs an extra call, so reserve it for short or low-confidence questions
    # where the phrasing gives the retriever least to work with.
    if use_hyde is None:
        vague = len(question.split()) <= VAGUE_QUERY_WORDS
        unsure = analysis is not None and analysis.confidence < 0.6
        use_hyde = vague or unsure

    if use_hyde:
        plan.hyde = _generate_hyde(question, session_id)

    log.info(
        "query expanded",
        extra={
            "queries": len(plan.search_queries()),
            "hyde": plan.hyde is not None,
        },
    )
    return plan
