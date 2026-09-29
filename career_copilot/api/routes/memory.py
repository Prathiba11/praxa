"""What the assistant remembers, and the means to correct it.

The delete endpoint is the point of this router. A memory feature the user
cannot inspect is a system forming opinions about them in private, and one they
cannot correct is worse - a preference they have since changed keeps shaping
answers with no way to say so. Every row is listed, every row says where it came
from, and every row can be removed.

Writing is deliberately narrow: a user may state a fact outright, and that is
all. Everything else arrives through `memory.extract` after a turn, which is the
only thing that reads a conversation.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from career_copilot.api.schemas import (
    CategoryUse,
    MemoryCategoryValue,
    MemoryFactOut,
    MemoryOrigin,
    MemoryPreview,
    RememberRequest,
)
from career_copilot.core.config import get_settings
from career_copilot.core.logging import get_logger
from career_copilot.core.security import mask_pii
from career_copilot.memory.recall import MAX_PROMPT_FACTS, recall_block
from career_copilot.storage import memory as store
from career_copilot.storage.db import init_db
from career_copilot.storage.models import MemoryFact

__all__ = ["router"]

log = get_logger(__name__)

router = APIRouter(tags=["memory"], prefix="/memory")


#: The database stores these as plain strings and the API promises closed sets.
#: A row written by an older version, or edited by hand, must not break the
#: listing - it falls back to the catch-all, because a fact the user can see
#: and delete is worth more than a page that refuses to load.
_CATEGORIES: tuple[MemoryCategoryValue, ...] = (
    "role",
    "location",
    "language",
    "must_have",
    "deal_breaker",
    "application",
    "other",
)


def _category_of(fact: MemoryFact) -> MemoryCategoryValue:
    for known in _CATEGORIES:
        if fact.category == known:
            return known
    return "other"


def _origin_of(fact: MemoryFact) -> MemoryOrigin:
    return "stated" if fact.origin == "stated" else "extracted"


def _out(fact: MemoryFact) -> MemoryFactOut:
    return MemoryFactOut(
        id=fact.id,
        category=_category_of(fact),
        text=fact.text,
        origin=_origin_of(fact),
        created_at=fact.created_at,
        last_seen_at=fact.last_seen_at,
    )


@router.get("", response_model=list[MemoryFactOut])
def list_memory() -> list[MemoryFactOut]:
    """Everything remembered, most recently mentioned first."""
    init_db()
    return [_out(fact) for fact in store.list_facts()]


@router.get("/preview", response_model=MemoryPreview)
def preview_memory() -> MemoryPreview:
    """The prompt text memory will contribute, and how full the store is.

    Read-only, and it calls `recall_block` rather than reimplementing it. That
    matters more than it looks: a preview assembled separately would drift from
    what the agent actually sends, and a preview that lies is worse than none -
    it would be a page that proves the wrong thing.
    """
    init_db()
    facts = store.list_facts(limit=store.MAX_TOTAL)
    counts: dict[str, int] = {}
    for fact in facts:
        key = _category_of(fact)
        counts[key] = counts.get(key, 0) + 1

    return MemoryPreview(
        block=recall_block(),
        enabled=get_settings().memory_enabled,
        stored=len(facts),
        max_stored=store.MAX_TOTAL,
        max_per_category=store.MAX_PER_CATEGORY,
        max_per_answer=MAX_PROMPT_FACTS,
        per_category=[
            CategoryUse(category=name, count=counts[name])
            for name in _CATEGORIES
            if counts.get(name)
        ],
        # `list_facts` returns most recently mentioned first, so the tail is the
        # one that has gone longest without coming up.
        least_recently_mentioned=facts[-1].text if facts else None,
    )


@router.post("", response_model=MemoryFactOut, status_code=201)
def remember(payload: RememberRequest) -> MemoryFactOut:
    """Record a fact the user stated outright.

    Marked `stated` rather than `extracted`, and the distinction is one-way:
    a fact told to us directly is never downgraded by being inferred again
    later. Masked on the way in, like anything else that reaches the store.
    """
    init_db()
    fact = store.remember(mask_pii(payload.text).text, category=payload.category, origin="stated")
    if fact is None:
        raise HTTPException(status_code=422, detail="That fact is empty.")
    return _out(fact)


@router.delete("/{fact_id}", status_code=204)
def forget(fact_id: int) -> None:
    """Delete one fact. It is the user's row, about the user's job search."""
    init_db()
    if not store.forget(fact_id):
        raise HTTPException(status_code=404, detail="No such fact.")
    log.info("fact forgotten", extra={"fact_id": fact_id})


@router.delete("", status_code=200)
def forget_all() -> dict[str, int]:
    """Forget everything. Returns how many rows went."""
    init_db()
    removed = store.clear()
    log.info("memory cleared", extra={"removed": removed})
    return {"removed": removed}
