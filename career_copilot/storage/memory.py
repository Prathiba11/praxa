"""Reading and writing what the assistant remembers about the user.

A repository, like `storage.jobs`: SQL and nothing else. What is worth
remembering is decided in `memory.extract`; how it is injected into a turn is
decided in `memory.recall`. This module only stores rows.

**The store is bounded.** A per-category cap, enforced on write, evicting the
least recently mentioned. Unbounded memory is how a context window fills with
facts from April, and how a preference the user has since changed outlives the
one that replaced it.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from career_copilot.core.logging import get_logger
from career_copilot.storage.db import session_scope
from career_copilot.storage.models import MemoryFact, fact_fingerprint

__all__ = [
    "MAX_PER_CATEGORY",
    "MAX_TOTAL",
    "clear",
    "count",
    "forget",
    "list_facts",
    "remember",
]

log = get_logger(__name__)

#: Facts kept per category before the least recently mentioned is dropped.
#: Six is enough to hold a real set of must-haves without any single category
#: crowding out the others in the prompt.
MAX_PER_CATEGORY = 6

#: A ceiling across all categories, so a new category cannot quietly enlarge
#: every prompt. Read alongside `recall.MAX_PROMPT_FACTS`, which is smaller -
#: what is stored and what is injected are different limits on purpose.
MAX_TOTAL = 30


def remember(text: str, *, category: str, origin: str = "extracted") -> MemoryFact | None:
    """Store one fact, or refresh it if it is already known.

    Returns the row, or None when the text is empty. Restating a known fact
    updates `last_seen_at` rather than inserting a duplicate - which is also
    what keeps a repeatedly-mentioned preference at the top of the store.
    """
    cleaned = " ".join(text.split())[:300]
    if not cleaned:
        return None

    fingerprint = fact_fingerprint(cleaned)
    with session_scope() as session:
        existing = session.scalar(select(MemoryFact).where(MemoryFact.fingerprint == fingerprint))
        if existing is not None:
            existing.last_seen_at = datetime.now(UTC)
            # A fact the user states outright outranks one that was inferred,
            # and the promotion is one-way: being re-inferred later must not
            # quietly downgrade something they told us directly.
            #
            # Both changes are made before the flush, and the row is detached
            # only after it. Expunging first would return an object claiming
            # `stated` while the database still said `extracted` - the page
            # would show the promotion until it was next reloaded.
            if origin == "stated" and existing.origin != "stated":
                existing.origin = "stated"
            session.flush()
            session.refresh(existing)
            session.expunge(existing)
            return existing

        fact = MemoryFact(fingerprint=fingerprint, category=category, text=cleaned, origin=origin)
        session.add(fact)
        session.flush()
        _evict(session, category)
        session.refresh(fact)
        session.expunge(fact)
        log.info("remembered", extra={"category": category, "origin": origin})
        return fact


def _evict(session: Session, category: str) -> None:
    """Drop the least recently mentioned rows over either cap.

    Runs inside the caller's transaction so a write and its eviction are one
    unit: a crash between them would otherwise leave the store over its limit
    with nothing to trigger a retry.
    """
    newest = select(MemoryFact.id).order_by(MemoryFact.last_seen_at.desc())

    keep_in_category = list(
        session.scalars(newest.where(MemoryFact.category == category).limit(MAX_PER_CATEGORY))
    )
    session.execute(
        delete(MemoryFact).where(
            MemoryFact.category == category, MemoryFact.id.notin_(keep_in_category)
        )
    )

    keep_overall = list(session.scalars(newest.limit(MAX_TOTAL)))
    session.execute(delete(MemoryFact).where(MemoryFact.id.notin_(keep_overall)))


def list_facts(category: str | None = None, limit: int = 100) -> list[MemoryFact]:
    """Everything remembered, most recently mentioned first."""
    with session_scope() as session:
        statement = select(MemoryFact).order_by(MemoryFact.last_seen_at.desc()).limit(limit)
        if category:
            statement = statement.where(MemoryFact.category == category)
        facts = list(session.scalars(statement))
        for fact in facts:
            session.expunge(fact)
        return facts


def forget(fact_id: int) -> bool:
    """Delete one fact. Returns whether there was one to delete.

    The user owns these rows. Deletion is a plain delete rather than a flag:
    a "forgotten" fact still sitting in the database would make the page a
    promise the storage layer does not keep.
    """
    with session_scope() as session:
        fact = session.get(MemoryFact, fact_id)
        if fact is None:
            return False
        session.delete(fact)
        return True


def clear() -> int:
    """Forget everything. Returns how many rows went."""
    with session_scope() as session:
        facts = list(session.scalars(select(MemoryFact)))
        for fact in facts:
            session.delete(fact)
        return len(facts)


def count() -> int:
    with session_scope() as session:
        return int(session.scalar(select(func.count()).select_from(MemoryFact)) or 0)
