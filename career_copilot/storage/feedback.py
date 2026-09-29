"""Ratings the user gave individual answers.

A repository, like `storage.memory`: SQL and nothing else. What a rating *means*
is not decided here, and deliberately nothing in this module feeds back into how
an answer is produced - that is a much harder feature, and claiming it on the
strength of a stored thumb would be claiming a loop that does not exist.

What this does give is the thing the loop would need first: a record of which
answers were wrong, in which mode, on which model, with the question that
produced them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from career_copilot.core.logging import get_logger
from career_copilot.storage.db import session_scope
from career_copilot.storage.models import ResponseFeedback

__all__ = [
    "MAX_STORED",
    "ModeTally",
    "Tally",
    "clear",
    "count",
    "list_feedback",
    "rate",
    "tally",
    "unrate",
]

log = get_logger(__name__)

#: Rated turns kept before the oldest are dropped. A rating is useful while you
#: can still remember the turn; a thousand of them is a dataset nobody reads.
#: The cap exists for the same reason the memory store has one.
MAX_STORED = 200

#: Question and answer are truncated to this before storage. The point of
#: keeping them is to recognise the turn again, not to archive it.
MAX_TEXT_CHARS = 4_000


@dataclass(frozen=True)
class ModeTally:
    mode: str
    up: int
    down: int


@dataclass(frozen=True)
class Tally:
    up: int
    down: int
    by_mode: tuple[ModeTally, ...]

    @property
    def total(self) -> int:
        return self.up + self.down


def rate(
    *,
    message_id: str,
    thread_id: str,
    rating: str,
    mode: str,
    model: str,
    question: str,
    answer: str,
) -> ResponseFeedback:
    """Record or replace the rating on one answer.

    Replace, not append: `message_id` is unique, so rating the same answer twice
    leaves one row holding the latest opinion. A user who clicks down and then
    up has changed their mind, and a tally that counted both would be counting
    clicks rather than answers.
    """
    with session_scope() as session:
        row = session.scalar(
            select(ResponseFeedback).where(ResponseFeedback.message_id == message_id)
        )
        if row is None:
            row = ResponseFeedback(message_id=message_id, thread_id=thread_id)
            session.add(row)

        row.rating = rating
        row.mode = mode
        row.model = model
        row.question = question[:MAX_TEXT_CHARS]
        row.answer = answer[:MAX_TEXT_CHARS]
        row.created_at = datetime.now(UTC)

        session.flush()
        _evict(session)
        session.refresh(row)
        session.expunge(row)
        log.info("answer rated", extra={"rating": rating, "mode": mode})
        return row


def _evict(session: Session) -> None:
    """Drop the oldest rows over the cap, inside the caller's transaction.

    Same reasoning as `storage.memory._evict`: a write and its eviction are one
    unit, so a crash between them cannot leave the store over its limit with
    nothing to trigger a retry.
    """
    keep = list(
        session.scalars(
            select(ResponseFeedback.id)
            .order_by(ResponseFeedback.created_at.desc())
            .limit(MAX_STORED)
        )
    )
    session.execute(delete(ResponseFeedback).where(ResponseFeedback.id.notin_(keep)))


def unrate(message_id: str) -> bool:
    """Remove the rating on one answer. Returns whether there was one."""
    with session_scope() as session:
        row = session.scalar(
            select(ResponseFeedback).where(ResponseFeedback.message_id == message_id)
        )
        if row is None:
            return False
        session.delete(row)
        return True


def list_feedback(rating: str | None = None, limit: int = 50) -> list[ResponseFeedback]:
    """Rated turns, most recent first."""
    with session_scope() as session:
        statement = (
            select(ResponseFeedback).order_by(ResponseFeedback.created_at.desc()).limit(limit)
        )
        if rating:
            statement = statement.where(ResponseFeedback.rating == rating)
        rows = list(session.scalars(statement))
        for row in rows:
            session.expunge(row)
        return rows


def tally() -> Tally:
    """How many up, how many down, and the same split per mode."""
    with session_scope() as session:
        rows = session.execute(
            select(ResponseFeedback.mode, ResponseFeedback.rating, func.count())
            .group_by(ResponseFeedback.mode, ResponseFeedback.rating)
            .order_by(ResponseFeedback.mode)
        ).all()

    per_mode: dict[str, dict[str, int]] = {}
    for mode, rating, number in rows:
        per_mode.setdefault(mode, {"up": 0, "down": 0})[rating] = int(number)

    return Tally(
        up=sum(counts["up"] for counts in per_mode.values()),
        down=sum(counts["down"] for counts in per_mode.values()),
        by_mode=tuple(
            ModeTally(mode=mode, up=counts["up"], down=counts["down"])
            for mode, counts in sorted(per_mode.items())
        ),
    )


def clear() -> int:
    """Remove every rating. Returns how many rows went."""
    with session_scope() as session:
        rows = list(session.scalars(select(ResponseFeedback)))
        for row in rows:
            session.delete(row)
        return len(rows)


def count() -> int:
    with session_scope() as session:
        return int(session.scalar(select(func.count()).select_from(ResponseFeedback)) or 0)
