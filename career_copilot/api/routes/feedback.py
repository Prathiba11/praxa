"""Rating an answer, and reading the ratings back.

The narrow half of the feedback task, on purpose. This records what the user
thought of an answer and shows it back to them. It does **not** change how the
next answer is produced: no prompt is rewritten, no example is retrieved, no
model is reweighted. An agent that learns from feedback is a separate piece of
work, and a stored thumb is not evidence of one.

What it is good for is the question a project like this cannot otherwise answer:
*which* answers were wrong. A tally alone would be a number with no way back to
the turn, so every rating carries the question and the answer it judged.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from career_copilot.api.schemas import (
    FeedbackOut,
    FeedbackSummary,
    Mode,
    ModeTallyOut,
    RateRequest,
    RatingValue,
)
from career_copilot.core.logging import get_logger
from career_copilot.core.security import mask_pii
from career_copilot.storage import feedback as store
from career_copilot.storage.db import init_db
from career_copilot.storage.models import ResponseFeedback

__all__ = ["router"]

log = get_logger(__name__)

router = APIRouter(tags=["feedback"], prefix="/feedback")

#: Rows are written as plain strings, so the listing must survive a value the
#: current build would not write - the same reasoning as `routes.memory`.
_MODES: tuple[Mode, ...] = ("chat", "jobs", "interview")


def _mode_of(value: str) -> Mode:
    for known in _MODES:
        if value == known:
            return known
    return "chat"


def _rating_of(value: str) -> RatingValue:
    return "up" if value == "up" else "down"


def _out(row: ResponseFeedback) -> FeedbackOut:
    return FeedbackOut(
        id=row.id,
        message_id=row.message_id,
        rating=_rating_of(row.rating),
        mode=_mode_of(row.mode),
        model=row.model,
        question=row.question,
        answer=row.answer,
        created_at=row.created_at,
    )


@router.post("", response_model=FeedbackOut, status_code=201)
def rate_answer(payload: RateRequest) -> FeedbackOut:
    """Record what the user thought of one answer, replacing any earlier view.

    Masked on the way in. The question is the user's own text and the answer can
    quote it back, so both go through `mask_pii` for the same reason memory does
    - this is a store, and what reaches a store is masked.
    """
    init_db()
    row = store.rate(
        message_id=payload.message_id,
        thread_id=payload.thread_id,
        rating=payload.rating,
        mode=payload.mode,
        model=payload.model,
        question=mask_pii(payload.question).text,
        answer=mask_pii(payload.answer).text,
    )
    return _out(row)


@router.delete("/{message_id}", status_code=204)
def unrate_answer(message_id: str) -> None:
    """Withdraw a rating. Clicking the same thumb again should undo it."""
    init_db()
    if not store.unrate(message_id):
        raise HTTPException(status_code=404, detail="That answer is not rated.")


@router.get("", response_model=FeedbackSummary)
def read_feedback(
    rating: RatingValue | None = None,
    limit: int = Query(default=20, ge=1, le=100),
) -> FeedbackSummary:
    """The tally, the split per mode, and the most recently rated turns."""
    init_db()
    counts = store.tally()
    rows = store.list_feedback(rating=rating, limit=limit)

    return FeedbackSummary(
        up=counts.up,
        down=counts.down,
        total=counts.total,
        approval=(counts.up / counts.total) if counts.total else None,
        max_stored=store.MAX_STORED,
        by_mode=[
            ModeTallyOut(mode=_mode_of(entry.mode), up=entry.up, down=entry.down)
            for entry in counts.by_mode
        ],
        recent=[_out(row) for row in rows],
    )


@router.delete("", status_code=200)
def clear_feedback() -> dict[str, int]:
    """Remove every rating. The rows are the user's, like every other store."""
    init_db()
    removed = store.clear()
    log.info("feedback cleared", extra={"removed": removed})
    return {"removed": removed}
