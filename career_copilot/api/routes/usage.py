"""What has been spent, and how much of that figure to trust.

Two ceilings exist and both matter. The session ceiling is the one a user
feels; the monthly ceiling is the one that actually protects the card, because
a session id is minted by the client and a client that rotates it resets its
own session ceiling. So this endpoint reports both, and `budgetRemainingUsd` is
the smaller of the two headrooms - the number that will stop the next turn.

`unpricedCalls` is the honesty field. A cost total assembled partly from calls
whose price nobody knows is an understatement, and showing the total without
showing that is worse than showing nothing.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from career_copilot.api.schemas import UsageSummary
from career_copilot.core.config import get_settings
from career_copilot.core.usage import SessionTotals, estimate_cost_usd, month_to_date_usd
from career_copilot.core.usage import session_totals as read_session_totals

__all__ = ["router"]

router = APIRouter(tags=["usage"])

# A nominal turn, used only to answer "what will the next question cost me?"
# before any have been asked. Two model calls - one that picks a tool, one that
# writes the answer - with a prompt dominated by retrieved passages.
_NOMINAL_CALLS_PER_ANSWER = 2
_NOMINAL_PROMPT_TOKENS = 3000
_NOMINAL_COMPLETION_TOKENS = 400


def _estimated_cost_per_answer(model: str) -> float:
    """Price-table arithmetic for one nominal turn.

    Returns 0.0 for a model that is not in the table, which is
    `estimate_cost_usd`'s documented behaviour and logs a warning there. The
    client shows this as an estimate, never as a charge.
    """
    return _NOMINAL_CALLS_PER_ANSWER * estimate_cost_usd(
        model, _NOMINAL_PROMPT_TOKENS, _NOMINAL_COMPLETION_TOKENS
    )


@router.get("/usage", response_model=UsageSummary)
def usage(
    thread_id: str | None = Query(default=None, alias="threadId"),
) -> UsageSummary:
    """Spend for one thread, plus the month-to-date figure that bounds it.

    Without a `threadId` the session figures are zero: there is no session to
    report on, and inventing one by summing every session would answer a
    question nobody asked.
    """
    settings = get_settings()
    totals = read_session_totals(thread_id) if thread_id else SessionTotals()
    month = month_to_date_usd()

    session_headroom = max(settings.session_budget_usd - totals.cost_usd, 0.0)
    month_headroom = max(settings.monthly_budget_usd - month, 0.0)

    return UsageSummary(
        session_tokens=totals.prompt_tokens + totals.completion_tokens,
        session_cost_usd=totals.cost_usd,
        session_budget_usd=settings.session_budget_usd,
        month_to_date_usd=month,
        monthly_budget_usd=settings.monthly_budget_usd,
        budget_remaining_usd=min(session_headroom, month_headroom),
        estimated_cost_per_answer_usd=_estimated_cost_per_answer(settings.chat_model),
        unpriced_calls=totals.unpriced_calls,
    )
